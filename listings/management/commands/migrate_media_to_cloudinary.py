import os
import logging
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.core.files import File
from django.core.files.storage import storages
from listings.models import Product

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Safely migrates locally stored media files (raw_image, refined_image, raw_audio) "
        "to centralized Cloudinary storage. Idempotent and non-destructive."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Simulate migration without uploading to Cloudinary or modifying database rows.',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Re-upload files even if they already exist in Cloudinary storage.',
        )
        parser.add_argument(
            '--product-id',
            type=int,
            default=None,
            help='Migrate media for a specific product ID only.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        force = options['force']
        product_id = options['product_id']

        self.stdout.write(self.style.MIGRATE_HEADING("=== Anantah Cloudinary Media Migration ==="))
        if dry_run:
            self.stdout.write(self.style.WARNING("Mode: DRY-RUN (No files will be uploaded, no DB rows modified)\n"))
        else:
            self.stdout.write(self.style.NOTICE("Mode: LIVE MIGRATION (Source local files will be preserved)\n"))

        # Verify Cloudinary configuration
        if not getattr(settings, 'CLOUDINARY_CONFIGURED', False):
            raise CommandError(
                "Cloudinary credentials (CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET) "
                "are not configured in settings/.env. Aborting migration."
            )

        default_storage = storages['default']
        audio_storage = storages['audio']

        if 'Cloudinary' not in default_storage.__class__.__name__:
            raise CommandError(
                f"Default storage is '{default_storage.__class__.__name__}', expected Cloudinary storage. "
                "Ensure STORAGES is configured correctly."
            )

        # Query products
        products = Product.objects.all().order_by('id')
        if product_id is not None:
            products = products.filter(id=product_id)

        total_products = products.count()
        self.stdout.write(f"Found {total_products} product(s) to process.\n")

        stats = {
            'total_products': total_products,
            'total_fields_scanned': 0,
            'already_migrated': 0,
            'uploaded': 0,
            'to_upload': 0,
            'missing_local': 0,
            'empty': 0,
            'failed': 0,
        }

        media_fields = [
            ('raw_image', default_storage),
            ('refined_image', default_storage),
            ('raw_audio', audio_storage),
        ]

        for product in products:
            self.stdout.write(self.style.HTTP_INFO(f"--- Product #{product.id}: '{product.title_en}' ---"))

            for field_name, target_storage in media_fields:
                field = getattr(product, field_name, None)
                stats['total_fields_scanned'] += 1

                if not field or not field.name:
                    stats['empty'] += 1
                    continue

                clean_rel_name = field.name.replace('\\', '/')
                # Strip leading 'media/' if accidentally present in field name
                if clean_rel_name.startswith('media/'):
                    lookup_name = clean_rel_name[6:]
                else:
                    lookup_name = clean_rel_name

                # 1. First check if asset is already present in Cloudinary storage
                is_already_on_cloud = False
                existing_cloud_ref = None
                if not force:
                    for check_name in [clean_rel_name, lookup_name]:
                        try:
                            if target_storage.exists(check_name):
                                is_already_on_cloud = True
                                existing_cloud_ref = check_name
                                break
                        except Exception as e:
                            logger.debug(f"Cloud existence check failed for {check_name}: {e}")

                if is_already_on_cloud:
                    cloud_url = target_storage.url(existing_cloud_ref)
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  [ALREADY MIGRATED] {field_name}: '{field.name}' exists on Cloudinary ({cloud_url})"
                        )
                    )
                    stats['already_migrated'] += 1
                    continue

                # 2. If not on Cloudinary, locate local file on disk under MEDIA_ROOT
                local_path = os.path.join(settings.MEDIA_ROOT, lookup_name)
                alt_local_path = os.path.join(settings.MEDIA_ROOT, clean_rel_name)

                if os.path.isfile(local_path):
                    resolved_path = local_path
                elif os.path.isfile(alt_local_path):
                    resolved_path = alt_local_path
                else:
                    resolved_path = None

                if not resolved_path:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  [MISSING LOCAL] {field_name}: '{field.name}' not found on local disk. "
                            f"Row left intact (may have been uploaded from another PC)."
                        )
                    )
                    stats['missing_local'] += 1
                    continue

                file_size_kb = round(os.path.getsize(resolved_path) / 1024, 2)

                if dry_run:
                    self.stdout.write(
                        f"  [DRY RUN] {field_name}: '{field.name}' ({file_size_kb} KB) -> would upload to Cloudinary."
                    )
                    stats['to_upload'] += 1
                    continue

                # Live upload to Cloudinary
                try:
                    self.stdout.write(f"  Uploading {field_name} ({field.name}, {file_size_kb} KB) to Cloudinary...")
                    with open(resolved_path, 'rb') as f:
                        file_obj = File(f)
                        saved_name = target_storage.save(lookup_name, file_obj)

                    # Verify upload succeeded
                    if target_storage.exists(saved_name):
                        if field.name != saved_name:
                            setattr(product, field_name, saved_name)
                            product.save(update_fields=[field_name])
                        cloud_url = target_storage.url(saved_name)
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"  [SUCCESS] {field_name} migrated -> {cloud_url}"
                            )
                        )
                        stats['uploaded'] += 1
                    else:
                        self.stdout.write(
                            self.style.ERROR(
                                f"  [ERROR] Upload verification failed for {field_name} ('{field.name}')"
                            )
                        )
                        stats['failed'] += 1
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(
                            f"  [FAILED] Upload exception for {field_name} ('{field.name}'): {e}"
                        )
                    )
                    stats['failed'] += 1

            self.stdout.write("")

        # Summary
        self.stdout.write(self.style.MIGRATE_HEADING("=== Migration Summary ==="))
        self.stdout.write(f"Products scanned:        {stats['total_products']}")
        self.stdout.write(f"Media fields scanned:    {stats['total_fields_scanned']}")
        self.stdout.write(f"Empty fields:            {stats['empty']}")
        self.stdout.write(f"Already on Cloudinary:   {stats['already_migrated']}")
        if dry_run:
            self.stdout.write(f"Ready for upload:        {stats['to_upload']}")
        else:
            self.stdout.write(f"Successfully uploaded:   {stats['uploaded']}")
            self.stdout.write(f"Failed uploads:          {stats['failed']}")
        self.stdout.write(f"Missing local files:     {stats['missing_local']}")
        self.stdout.write(self.style.MIGRATE_HEADING("========================="))

        if stats['failed'] > 0:
            self.stdout.write(self.style.ERROR("Migration finished with errors."))
        elif dry_run:
            self.stdout.write(self.style.SUCCESS("Dry run completed successfully. Run without --dry-run to execute."))
        else:
            self.stdout.write(self.style.SUCCESS("Media migration completed successfully!"))
