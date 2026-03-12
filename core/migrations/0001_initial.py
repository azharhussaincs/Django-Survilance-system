"""
Initial migration – creates nvr and camera tables.
"""
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='NVR',
            fields=[
                ('id',            models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('location',      models.CharField(help_text='Physical/logical location label', max_length=255)),
                ('url',           models.CharField(help_text='Base URL of NVR web interface', max_length=500)),
                ('port',          models.PositiveIntegerField(blank=True, help_text='Port if not included in URL', null=True)),
                ('username',      models.CharField(max_length=150)),
                ('password',      models.CharField(max_length=255)),
                ('brand',         models.CharField(choices=[('hikvision','Hikvision'),('cpplus','CP Plus'),('dahua','Dahua'),('generic','Generic'),('unknown','Unknown')], default='unknown', max_length=50)),
                ('status',        models.CharField(choices=[('connected','Connected'),('disconnected','Disconnected'),('error','Error'),('pending','Pending')], default='pending', max_length=20)),
                ('is_connected',  models.BooleanField(default=False)),
                ('last_connected',models.DateTimeField(blank=True, null=True)),
                ('error_message', models.TextField(blank=True, default='')),
                ('created_at',    models.DateTimeField(default=django.utils.timezone.now)),
                ('updated_at',    models.DateTimeField(auto_now=True)),
                ('notes',         models.TextField(blank=True, default='')),
            ],
            options={'db_table': 'nvr', 'ordering': ['-created_at'], 'verbose_name': 'NVR', 'verbose_name_plural': 'NVRs'},
        ),
        migrations.CreateModel(
            name='Camera',
            fields=[
                ('id',           models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nvr',          models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='cameras', to='core.nvr')),
                ('name',         models.CharField(max_length=255)),
                ('camera_id',    models.CharField(blank=True, default='', help_text='Channel ID from NVR', max_length=100)),
                ('preview_path', models.CharField(blank=True, default='/', help_text='Relative path or full URL to the preview page', max_length=500)),
                ('channel',      models.PositiveIntegerField(blank=True, help_text='Channel number on NVR', null=True)),
                ('is_active',    models.BooleanField(default=True)),
                ('created_at',   models.DateTimeField(default=django.utils.timezone.now)),
                ('updated_at',   models.DateTimeField(auto_now=True)),
            ],
            options={'db_table': 'camera', 'ordering': ['nvr', 'channel', 'name'], 'verbose_name': 'Camera', 'verbose_name_plural': 'Cameras'},
        ),
        migrations.AlterUniqueTogether(
            name='camera',
            unique_together={('nvr', 'camera_id')},
        ),
    ]
