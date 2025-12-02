"""
Smart media deduplication script.
Finds duplicate media files (same base name) and reuses identical ones based on file size.
"""

import os
import sqlite3
import logging
from collections import defaultdict
from pathlib import Path

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def get_database_path() -> str:
    """Get database path from environment or use default."""
    backup_path = os.getenv('BACKUP_PATH', '/data/backups')
    return os.path.join(backup_path, 'telegram_backup.db')


def strip_message_id_from_filename(filename: str) -> str:
    """Strip message_id prefix from filename."""
    parts = filename.split('_', 1)
    if len(parts) == 2 and parts[0].isdigit():
        return parts[1]
    return filename


def deduplicate_media(db_path: str, dry_run: bool = False):
    """
    Smart deduplication: Find identical files and reuse them.
    
    Args:
        db_path: Path to SQLite database
        dry_run: If True, only show what would be done
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Get all messages with media
    cursor.execute('''
        SELECT 
            m.id as message_id,
            m.chat_id,
            m.media_path,
            m.media_type
        FROM messages m
        WHERE m.media_path IS NOT NULL AND m.media_path != ''
        ORDER BY m.chat_id, m.id
    ''')
    
    messages = cursor.fetchall()
    logger.info(f"Found {len(messages)} messages with media paths")
    
    # Group by base filename
    filename_groups = defaultdict(list)
    
    for msg in messages:
        if not msg['media_path']:
            continue
            
        full_path = msg['media_path']
        filename = os.path.basename(full_path)
        base_filename = strip_message_id_from_filename(filename)
        
        file_size = os.path.getsize(full_path) if os.path.exists(full_path) else None
        
        filename_groups[base_filename].append({
            'message_id': msg['message_id'],
            'chat_id': msg['chat_id'],
            'full_path': full_path,
            'filename': filename,
            'file_size': file_size,
            'exists': os.path.exists(full_path)
        })
    
    # Find duplicates
    duplicates = {k: v for k, v in filename_groups.items() if len(v) > 1}
    
    if not duplicates:
        logger.info("✅ No duplicate filenames found!")
        conn.close()
        return
    
    logger.info(f"\n🔍 Found {len(duplicates)} duplicate base filenames")
    
    total_reused = 0
    total_missing = 0
    total_kept = 0
    
    for base_name, files in duplicates.items():
        # Group by file size
        size_groups = defaultdict(list)
        for f in files:
            if f['exists'] and f['file_size'] is not None:
                size_groups[f['file_size']].append(f)
            else:
                size_groups['missing'].append(f)
        
        logger.info(f"\n📁 '{base_name}' ({len(files)} total)")
        
        # Handle each size group
        for size, group in size_groups.items():
            if size == 'missing':
                logger.info(f"   ⚠️  Missing files: {len(group)}")
                for f in group:
                    logger.info(f"      - Message {f['message_id']}: {f['filename']}")
                total_missing += len(group)
                continue
            
            if len(group) == 1:
                # Only one file of this size
                logger.info(f"   ✓ Unique ({size} bytes): {group[0]['filename']}")
                total_kept += 1
                continue
            
            # Multiple files with same size - assume identical
            logger.info(f"   🔗 Identical ({size} bytes): {len(group)} copies")
            
            # Keep the first one, update others to point to it
            keeper = group[0]
            logger.info(f"      ✓ Keeper: {keeper['filename']} (Message {keeper['message_id']})")
            total_kept += 1
            
            for dupe in group[1:]:
                logger.info(f"      → Reuse for: Message {dupe['message_id']}")
                
                if not dry_run:
                    # Delete duplicate file
                    if os.path.exists(dupe['full_path']) and dupe['full_path'] != keeper['full_path']:
                        try:
                            os.remove(dupe['full_path'])
                            logger.info(f"         Deleted: {dupe['filename']}")
                        except Exception as e:
                            logger.error(f"         Failed to delete: {e}")
                    
                    # Update database to point to keeper's file
                    try:
                        cursor.execute('''
                            UPDATE messages 
                            SET media_path = ? 
                            WHERE id = ? AND chat_id = ?
                        ''', (keeper['full_path'], dupe['message_id'], dupe['chat_id']))
                        
                        total_reused += 1
                    except Exception as e:
                        logger.error(f"         Failed to update database: {e}")
    
    if not dry_run:
        conn.commit()
    
    conn.close()
    
    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("Summary:")
    logger.info(f"  Duplicate base filenames: {len(duplicates)}")
    logger.info(f"  Files kept: {total_kept}")
    logger.info(f"  Files reused: {total_reused}")
    logger.info(f"  Files missing (need re-download): {total_missing}")
    
    if not dry_run:
        logger.info("\n✅ Deduplication complete!")
        if total_missing > 0:
            logger.info(f"⚠️  {total_missing} files are missing - run a backup to download them")
    else:
        logger.info("\n[DRY RUN] No changes made. Run without --dry-run to apply.")
    
    logger.info("=" * 60)


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Smart media deduplication')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done')
    parser.add_argument('--db-path', help='Path to database file')
    
    args = parser.parse_args()
    
    db_path = args.db_path or get_database_path()
    
    logger.info(f"Database: {db_path}")
    
    if not os.path.exists(db_path):
        logger.error(f"Database not found: {db_path}")
        exit(1)
    
    if args.dry_run:
        logger.info("Running in DRY RUN mode\n")
    
    deduplicate_media(db_path, dry_run=args.dry_run)
