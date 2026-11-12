"""Validation and field metadata for the allow-listed staff resources."""
import os

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.files.uploadedfile import UploadedFile
from rest_framework import serializers

from accounts.models import User
from rest_framework.exceptions import ValidationError

from content.models import MediaAsset
from .registry import Resource


MAX_UPLOAD_MB = max(1, settings.MAX_FILE_UPLOAD_SIZE // (1024 * 1024))   # one cap for the whole project (env: MAX_FILE_UPLOAD_SIZE)
ALLOWED_UPLOADS = {
    '.jpg', '.jpeg', '.png', '.webp', '.gif', '.pdf', '.csv', '.txt',
    '.doc', '.docx', '.xls', '.xlsx', '.mp4',
}
IMAGE_UPLOADS = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}


def validate_upload(upload: UploadedFile):
    """Staff uploads: size cap, extension allow-list, and a real decode for images (a renamed .exe is not an image)."""
    ext = os.path.splitext(upload.name)[1].lower()
    if ext not in ALLOWED_UPLOADS:
        raise serializers.ValidationError(f'{ext or "This"} files are not allowed. Allowed: ' + ', '.join(sorted(ALLOWED_UPLOADS)) + '.')
    if upload.size > MAX_UPLOAD_MB * 1024 * 1024:
        raise serializers.ValidationError(f'File is too large (max {MAX_UPLOAD_MB} MB).')
    if ext in IMAGE_UPLOADS:
        from PIL import Image
        try:
            Image.open(upload).verify()
        except Exception as exc:   # noqa: BLE001 - any decode failure means "not a usable image"
            raise serializers.ValidationError('This file is not a valid image.') from exc
        finally:
            upload.seek(0)


def resource_serializer(resource: Resource):
    if resource.fields:
        # the panel addresses every row by its primary key, so always include it
        pk = resource.model._meta.pk.name
        fields = resource.fields if pk in resource.fields else (pk, *resource.fields)
    elif resource.exclude_fields:
        # DRF rejects fields='__all__' together with exclude, so list every model field except the hidden ones.
        names = [f.name for f in resource.model._meta.fields] + [f.name for f in resource.model._meta.many_to_many]
        fields = tuple(n for n in names if n not in resource.exclude_fields)
    else:
        fields = '__all__'
    meta = type('Meta', (), {
        'model': resource.model,
        'fields': fields,
        'read_only_fields': tuple(set(resource.read_only_fields) | {'tenant'} | ({'status', 'publish_at', 'published_at'} if resource.model.__name__ in {'Trip', 'Destination', 'CmsPage', 'Blog', 'Event'} else set())),
    })
    return type(f'{resource.model.__name__}AdminSerializer', (ValidatedModelSerializer,), {'Meta': meta})


class ValidatedModelSerializer(serializers.ModelSerializer):
    """ModelSerializer that runs Django model validation before persisting."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        tenant = getattr(self.context.get('request'), 'tenant', None)
        if tenant is None:
            return
        for field in self.fields.values():
            relation = field.child_relation if isinstance(field, serializers.ManyRelatedField) else field
            if (
                isinstance(relation, serializers.PrimaryKeyRelatedField)
                and relation.queryset is not None
                and relation.queryset.model is User
            ):
                relation.queryset = relation.queryset.filter(
                    tenant_memberships__tenant=tenant,
                    tenant_memberships__is_active=True,
                )

    def validate(self, attrs):
        for value in attrs.values():
            if isinstance(value, UploadedFile):
                validate_upload(value)
        return super().validate(attrs)

    def _clean(self, instance):
        excluded = [field.name for field in instance._meta.fields if not field.editable]
        excluded += [field.name for field in instance._meta.many_to_many]
        try:
            instance.full_clean(exclude=excluded)
        except DjangoValidationError as exc:
            if hasattr(exc, 'message_dict'):
                raise ValidationError(exc.message_dict) from exc
            raise ValidationError({'non_field_errors': exc.messages}) from exc

    def create(self, validated_data):
        model = self.Meta.model
        m2m_data = {name: validated_data.pop(name) for name in list(validated_data) if name in {f.name for f in model._meta.many_to_many}}
        instance = model(**validated_data)
        self._clean(instance)
        instance.save()
        for name, value in m2m_data.items():
            getattr(instance, name).set(value)
        return instance

    def update(self, instance, validated_data):
        model = self.Meta.model
        m2m_names = {f.name for f in model._meta.many_to_many}
        m2m_data = {name: validated_data.pop(name) for name in list(validated_data) if name in m2m_names}
        for name, value in validated_data.items():
            setattr(instance, name, value)
        self._clean(instance)
        instance.save()
        for name, value in m2m_data.items():
            getattr(instance, name).set(value)
        return instance


def _kind(field):
    if getattr(field, 'choices', None):
        return 'choice'
    if isinstance(field, serializers.ManyRelatedField):
        return 'relation-many'
    if isinstance(field, serializers.PrimaryKeyRelatedField):
        return 'relation'
    if isinstance(field, serializers.BooleanField):
        return 'boolean'
    if isinstance(field, serializers.IntegerField):
        return 'integer'
    if isinstance(field, serializers.DecimalField):
        return 'decimal'
    if isinstance(field, serializers.DateTimeField):
        return 'datetime'
    if isinstance(field, serializers.DateField):
        return 'date'
    if isinstance(field, serializers.JSONField):
        return 'json'
    if isinstance(field, serializers.FileField):
        return 'file'
    if isinstance(field, serializers.EmailField):
        return 'email'
    if isinstance(field, serializers.URLField):
        return 'url'
    if isinstance(field, serializers.CharField) and getattr(field, 'style', {}).get('base_template') == 'textarea.html':
        return 'text'
    return 'string'


def schema_for(resource: Resource, request=None):
    serializer_class = resource_serializer(resource)
    serializer = serializer_class(context={'request': request})
    fields = []
    for name, field in serializer.fields.items():
        if name in {'url'}:
            continue
        value = {
            'name': name,
            'label': str(field.label or name.replace('_', ' ').title()),
            'type': _kind(field),
            'required': bool(field.required and not field.read_only),
            'read_only': bool(field.read_only),
            'allow_null': bool(getattr(field, 'allow_null', False)),
            'help_text': str(field.help_text or ''),
        }
        if value['type'] == 'file':
            value['max_mb'] = MAX_UPLOAD_MB
            value['accept'] = ','.join(sorted(ALLOWED_UPLOADS))
        choices = getattr(field, 'choices', None)
        if choices:
            value['choices'] = [{'value': key, 'label': str(label)} for key, label in choices.items()]
        relation = field.child_relation if isinstance(field, serializers.ManyRelatedField) else field
        if isinstance(relation, serializers.PrimaryKeyRelatedField):
            value['many'] = isinstance(field, serializers.ManyRelatedField)
            qs = relation.get_queryset()
            if qs is not None and qs.model is MediaAsset:
                value['media'] = True   # the admin shows an image upload box instead of a dropdown
            if qs is not None and qs.count() <= 200:
                options = []
                for obj in qs[:200]:
                    option = {'value': str(obj.pk), 'label': str(obj)}
                    if isinstance(obj, MediaAsset):
                        filename = obj.file.name.rsplit('/', 1)[-1] if obj.file else ''
                        extension = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
                        image_extension = f'.{extension}'
                        option['label'] = (
                            f'Invalid image · {filename}' if obj.kind == 'image' and image_extension not in IMAGE_UPLOADS
                            else obj.alt_text or filename or 'Media asset'
                        )
                        option['media_kind'] = obj.kind
                        if obj.kind == 'image' and image_extension in IMAGE_UPLOADS and obj.file:
                            try:
                                image_url = obj.file.url
                                option['image_preview_url'] = request.build_absolute_uri(image_url) if request else image_url
                            except (ValueError, OSError):
                                pass
                    options.append(option)
                value['options'] = options
        fields.append(value)
    return {
        'key': resource.key,
        'module': resource.module,
        'label': resource.label,
        'mode': resource.mode,
        'pk': resource.model._meta.pk.name,
        'fields': fields,
    }
