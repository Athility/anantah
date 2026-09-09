#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt

echo "=== DIAGNOSTIC: checking Django admin static files ==="
python -c "
import django, os
admin_img_dir = os.path.join(os.path.dirname(django.__file__), 'contrib', 'admin', 'static', 'admin', 'img')
print('Django installed at:', os.path.dirname(django.__file__))
print('Admin img directory exists:', os.path.isdir(admin_img_dir))
if os.path.isdir(admin_img_dir):
    files = sorted(os.listdir(admin_img_dir))
    print('Total files found:', len(files))
    print('sorting-icons.svg present:', 'sorting-icons.svg' in files)
    print('All files:', files)
else:
    print('Admin img directory does not exist at all.')
"
echo "=== END DIAGNOSTIC ==="

python manage.py collectstatic --noinput --clear
python manage.py migrate