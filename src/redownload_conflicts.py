"""
Find and re-download media files that had naming conflicts.
Identifies files with duplicate base names, deletes them, and marks for re-download.
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
    """
    Strip message_id prefix from filename.
    E.g., '12345_photo.png' -> 'photo.png'
    """
    parts = filename.split('_', 1)
    if len(parts) == 2 and parts[0].isdigit():
        return parts[1]
    return filename


def find_and_fix_conflicts(db_path: str, dry_run: bool = False):
    """
    Find media files with duplicate base names and mark for re-download.
    
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
        WHERE m.media_path IS NOT NULL
        ORDER BY m.chat_id, m.id
    ''')
    
    messages = cursor.fetchall()
    logger.info(f"Found {len(messages)} messages with media")
    
    # Group by base filename (without message_id)
    filename_groups = defaultdict(list)
    
    for msg in messages:
        if not msg['media_path']:
            continue
            
        filename = os.path.basename(msg['media_path'])
        base_filename = strip_message_id_from_filename(filename)
        
        filename_groups[base_filename].append({
            'message_id': msg['message_id'],
            'chat_id': msg['chat_id'],
            'full_path': msg['media_path'],
            'filename': filename
        })
    
    # Find duplicates
    duplicates = {k: v for k, v in filename_groups.items() if len(v) > 1}
    
    if not duplicates:
        logger.info("✅ No duplicate filenames found!")
        conn.close()
        return
    
    logger.info(f"\n🔍 Found {len(duplicates)} duplicate base filenames affecting {sum(len(v) for v in duplicates.values())} files")
    
    total_deleted = 0
    total_marked = 0
    
    for base_name, files in duplicates.items():
        logger.info(f"\n📁 Duplicate: '{base_name}' ({len(files)} occurrences)")
        
        for file_info in files:
            logger.info(f"   - Message {file_info['message_id']} (Chat {file_info['chat_id']}): {file_info['filename']}")
            
            if dry_run:
                logger.info(f"     [DRY RUN] Would delete and mark for re-download")
            else:
                # Delete file if exists
                if os.path.exists(file_info['full_path']):
                    try:
                        os.remove(file_info['full_path'])
                        logger.info(f"     ✓ Deleted file")
                        total_deleted += 1
                    except Exception as e:
                        logger.error(f"     ✗ Failed to delete: {e}")
                else:
                    logger.info(f"     ⊘ File not found (already deleted)")
                
                # Update database to mark as not downloaded
                try:
                    cursor.execute('''
                        UPDATE messages 
                        SET media_path = NULL
                        WHERE id = ? AND chat_id = ?
                    ''', (file_info['message_id'], file_info['chat_id']))
                    
                    logger.info(f"     ✓ Marked for re-download")
                    total_marked += 1
                except Exception as e:
                    logger.error(f"     ✗ Failed to update database: {e}")
    
    if not dry_run:
        conn.commit()
    
    conn.close()
    
    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("Summary:")
    logger.info(f"  Duplicate base filenames: {len(duplicates)}")
    logger.info(f"  Total affected files: {sum(len(v) for v in duplicates.values())}")
    
    if not dry_run:
        logger.info(f"  Files deleted: {total_deleted}")
        logger.info(f"  Messages marked for re-download: {total_marked}")
        logger.info("\n✅ Run your backup again to re-download the affected files")
    else:
        logger.info("\n[DRY RUN] No changes made. Run without --dry-run to apply.")
    
    logger.info("=" * 60)


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Fix duplicate media files by re-downloading')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')
    parser.add_argument('--db-path', help='Path to database file (overrides BACKUP_PATH env)')
    
    args = parser.parse_args()
    
    db_path = args.db_path or get_database_path()
    
    logger.info(f"Database: {db_path}")
    
    if not os.path.exists(db_path):
        logger.error(f"Database not found: {db_path}")
        exit(1)
    
    if args.dry_run:
        logger.info("Running in DRY RUN mode - no changes will be made\n")
    
    find_and_fix_conflicts(db_path, dry_run=args.dry_run)
