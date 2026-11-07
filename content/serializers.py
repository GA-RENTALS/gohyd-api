from rest_framework import serializers

from . import models as m


def pick(obj, lang, field):
    """Language-specific text with English fallback (only PUBLISHED translations are exposed)."""
    rows = {t.language: t for t in obj.translations.all() if t.status == m.ContentStatus.PUBLISHED}
    t = rows.get(lang) or rows.get('en')
    return getattr(t, field, '') if t else ''


class DestinationSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    summary = serializers.SerializerMethodField()
    body = serializers.SerializerMethodField()
    seo = serializers.SerializerMethodField()
    cover_url = serializers.SerializerMethodField()

    class Meta:
        model = m.Destination
        fields = ('id', 'slug', 'region', 'latitude', 'longitude', 'distance_km_from_city', 'is_hyderabad_explore',
                  'name', 'summary', 'body', 'seo', 'cover_url')

    def _lang(self): return self.context.get('lang', 'en')
    def get_name(self, o): return pick(o, self._lang(), 'title')
    def get_summary(self, o): return pick(o, self._lang(), 'summary')
    def get_body(self, o): return pick(o, self._lang(), 'body')
    def get_seo(self, o): return {'title': pick(o, self._lang(), 'seo_title'), 'description': pick(o, self._lang(), 'seo_description')}
    def get_cover_url(self, o):
        if not o.cover_id or not o.cover.file:
            return None
        url = o.cover.file.url
        request = self.context.get('request')
        return request.build_absolute_uri(url) if request else url


class BlogSerializer(serializers.ModelSerializer):
    title = serializers.SerializerMethodField()
    summary = serializers.SerializerMethodField()
    body = serializers.SerializerMethodField()

    class Meta:
        model = m.Blog
        fields = ('id', 'slug', 'published_at', 'title', 'summary', 'body')

    def get_title(self, o): return pick(o, self.context.get('lang', 'en'), 'title')
    def get_summary(self, o): return pick(o, self.context.get('lang', 'en'), 'summary')
    def get_body(self, o): return pick(o, self.context.get('lang', 'en'), 'body')


class CmsPageSerializer(serializers.ModelSerializer):
    title = serializers.SerializerMethodField()
    body = serializers.SerializerMethodField()
    blocks = serializers.SerializerMethodField()

    class Meta:
        model = m.CmsPage
        fields = ('slug', 'kind', 'title', 'body', 'blocks')

    def get_title(self, o): return pick(o, self.context.get('lang', 'en'), 'title')
    def get_body(self, o): return pick(o, self.context.get('lang', 'en'), 'body')
    def get_blocks(self, o):
        lang = self.context.get('lang', 'en')
        rows = {t.language: t for t in o.translations.all() if t.status == m.ContentStatus.PUBLISHED}
        t = rows.get(lang) or rows.get('en')
        return {**(o.blocks_schema or {}), **(t.blocks if t else {})}


class FAQSerializer(serializers.ModelSerializer):
    question = serializers.SerializerMethodField()
    answer = serializers.SerializerMethodField()

    class Meta:
        model = m.FAQ
        fields = ('id', 'question', 'answer')

    def get_question(self, o):
        return getattr(o, f"question_{self.context.get('lang', 'en')}", '') or o.question_en
    def get_answer(self, o):
        return getattr(o, f"answer_{self.context.get('lang', 'en')}", '') or o.answer_en


class TestimonialSerializer(serializers.ModelSerializer):
    quote = serializers.SerializerMethodField()

    class Meta:
        model = m.Testimonial
        fields = ('id', 'author_name', 'author_role', 'quote')

    def get_quote(self, o):
        return getattr(o, f"quote_{self.context.get('lang', 'en')}", '') or o.quote_en
