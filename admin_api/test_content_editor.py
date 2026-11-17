"""The content editor (blog posts, website pages, destinations): add with a title, one page each, publish, safe delete, safe HTML."""
from django.test import SimpleTestCase
from rest_framework.test import APIClient

from content.html import clean_html
from content.models import Blog, BlogCategory, BlogTag, BlogTranslation, CmsPage, ContentStatus, Destination
from core.models import AuditLog
from core.testing import TenantTestCase, make_user

CATALOG = '/api/v1/admin/content/blogs/'


def overview(pk, kind='blogs'):
    return f'/api/v1/admin/content/{kind}/{pk}/'


class BlogAdminTests(TenantTestCase):
    def setUp(self):
        self.staff = make_user('+919811111111', is_staff=True, is_superuser=True, full_name='Staff One')
        self.client_ = APIClient()
        self.client_.force_authenticate(self.staff)

    def _create(self, title='Monsoon treks near Hyderabad'):
        res = self.client_.post(CATALOG, {'title': title}, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        return Blog.objects.get(pk=res.data['id'])

    def _transition(self, blog, status):
        return self.client_.post('/api/v1/admin/actions/content-transition/', {'resource': 'blogs', 'id': str(blog.pk), 'status': status}, format='json')

    # ---- add ----
    def test_adding_a_post_needs_only_a_title_and_creates_its_english_text(self):
        blog = self._create()
        self.assertEqual((blog.slug, blog.status, blog.author), ('monsoon-treks-near-hyderabad', ContentStatus.DRAFT, self.staff))
        self.assertEqual(list(blog.translations.values_list('language', 'title')), [('en', 'Monsoon treks near Hyderabad')])
        self.assertTrue(AuditLog.objects.filter(action='blogs.create', entity_id=str(blog.pk)).exists())

    def test_the_same_title_twice_gets_a_different_address(self):
        self.assertEqual(self._create('Food walk').slug, 'food-walk')
        self.assertEqual(self._create('Food walk').slug, 'food-walk-2')

    def test_a_title_is_required(self):
        res = self.client_.post(CATALOG, {'title': '   '}, format='json')
        self.assertEqual(res.status_code, 400)
        self.assertIn('title', res.data)
        self.assertFalse(Blog.objects.exists())

    def test_staff_without_permission_cannot_add_or_delete(self):
        blog = self._create()
        other = APIClient()
        other.force_authenticate(make_user('+919833333333', is_staff=True))
        self.assertEqual(other.post(CATALOG, {'title': 'Nope'}, format='json').status_code, 403)
        self.assertEqual(other.delete(overview(blog.pk)).status_code, 403)
        self.assertEqual(Blog.objects.count(), 1)

    # ---- list and page ----
    def test_list_and_page_show_the_post_with_its_languages_and_options(self):
        BlogCategory.objects.create(slug='guides', name='Guides')
        BlogTag.objects.create(slug='treks', name='Treks')
        blog = self._create()
        BlogTranslation.objects.create(blog=blog, language='te', title='వర్షాకాలం ట్రెక్‌లు')

        card = self.client_.get(CATALOG).data
        self.assertTrue(card['can_create'])
        self.assertEqual((card['results'][0]['title'], card['results'][0]['languages']), ('Monsoon treks near Hyderabad', ['en', 'te']))

        page = self.client_.get(overview(blog.pk)).data
        self.assertEqual(set(page['translations']), {'en', 'te'})
        self.assertEqual([c['name'] for c in page['options']['categories']], ['Guides'])
        self.assertEqual([t['name'] for t in page['options']['tags']], ['Treks'])
        self.assertTrue(all(page['permissions'].values()))
        self.assertFalse(page['slug_locked'])

    def test_search_finds_a_post_by_title_and_links_to_its_page(self):
        blog = self._create()
        hits = self.client_.get('/api/v1/admin/search/?q=monsoon').data['results']
        self.assertIn({'type': 'Blog post', 'label': 'Monsoon treks near Hyderabad', 'sub': 'Draft', 'href': f'/admin/overview/blog/{blog.pk}'}, hits)

    def test_unknown_post_is_404(self):
        self.assertEqual(self.client_.get(overview('not-a-uuid')).status_code, 404)

    # ---- publish ----
    def test_publish_puts_the_post_on_the_website_and_unpublish_takes_it_off(self):
        blog = self._create()
        self.assertEqual(self._transition(blog, 'PUBLISHED').status_code, 200)
        public = APIClient().get('/api/v1/blogs/').data['results']
        self.assertEqual([p['slug'] for p in public], [blog.slug])
        self.assertTrue(self.client_.get(overview(blog.pk)).data['slug_locked'])

        self.assertEqual(self._transition(blog, 'DRAFT').status_code, 200)
        self.assertEqual(APIClient().get('/api/v1/blogs/').data['results'], [])

    # ---- delete ----
    def test_a_draft_post_can_be_deleted(self):
        blog = self._create()
        self.assertEqual(self.client_.delete(overview(blog.pk)).status_code, 204)
        self.assertFalse(Blog.objects.filter(pk=blog.pk).exists())
        self.assertFalse(BlogTranslation.objects.filter(blog_id=blog.pk).exists())
        self.assertTrue(AuditLog.objects.filter(action='blogs.delete', entity_id=str(blog.pk)).exists())

    def test_a_published_post_must_be_unpublished_before_deleting(self):
        blog = self._create()
        self._transition(blog, 'PUBLISHED')
        res = self.client_.delete(overview(blog.pk))
        self.assertEqual(res.status_code, 409)
        self.assertIn('Unpublish', res.data['detail'])
        self.assertTrue(Blog.objects.filter(pk=blog.pk).exists())

    # ---- text ----
    def test_saved_text_keeps_formatting_but_not_scripts(self):
        blog = self._create()
        en = blog.translations.get(language='en')
        res = self.client_.patch(f'/api/v1/admin/resources/blog-translations/{en.pk}/', {
            'body': '<h2>Day 1</h2><p onclick="x()">Start at <b>6 am</b><script>alert(1)</script></p>'
                    '<p><a href="javascript:alert(1)">bad</a> <a href="https://goadventure.in">good</a></p>',
        }, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        en.refresh_from_db()
        self.assertIn('<h2>Day 1</h2>', en.body)
        self.assertIn('<strong>6 am</strong>', en.body)
        self.assertNotIn('script', en.body)
        self.assertNotIn('onclick', en.body)
        self.assertNotIn('javascript', en.body)
        self.assertIn('href="https://goadventure.in"', en.body)

    def test_public_api_returns_cover_seo_category_and_tags(self):
        category = BlogCategory.objects.create(slug='guides', name='Guides')
        blog = self._create()
        blog.category = category
        blog.save()
        blog.tags.add(BlogTag.objects.create(slug='treks', name='Treks'))
        blog.translations.filter(language='en').update(seo_title='Best monsoon treks', summary='Short list')
        self._transition(blog, 'PUBLISHED')
        post = APIClient().get(f'/api/v1/blogs/{blog.slug}/').data
        self.assertEqual(post['seo']['title'], 'Best monsoon treks')
        self.assertEqual(post['category'], {'slug': 'guides', 'name': 'Guides'})
        self.assertEqual(post['tags'], [{'slug': 'treks', 'name': 'Treks'}])
        self.assertIsNone(post['cover_url'])


class PageAndDestinationEditorTests(TenantTestCase):
    """Website pages and destinations use the same editor as blog posts."""

    def setUp(self):
        self.staff = make_user('+919811111111', is_staff=True, is_superuser=True, full_name='Staff One')
        self.client_ = APIClient()
        self.client_.force_authenticate(self.staff)

    def _publish(self, resource, pk):
        res = self.client_.post('/api/v1/admin/actions/content-transition/', {'resource': resource, 'id': str(pk), 'status': 'PUBLISHED'}, format='json')
        self.assertEqual(res.status_code, 200, res.data)

    def test_a_policy_page_can_be_added_at_its_fixed_address_and_shows_on_the_website(self):
        res = self.client_.post('/api/v1/admin/content/pages/', {'title': 'Privacy policy', 'slug': 'privacy'}, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        page = CmsPage.objects.get(pk=res.data['id'])
        self.assertEqual(page.slug, 'privacy')
        detail = self.client_.get(overview(page.pk, 'pages')).data
        self.assertTrue(detail['slug_locked'])            # the site links to /privacy, so its address can't change
        self.assertEqual(detail['public_url'], '/privacy')
        text = page.translations.get(language='en')
        self.client_.patch(f'/api/v1/admin/resources/cms-translations/{text.pk}/', {'body': 'We keep your data safe.<script>x</script>'}, format='json')
        self._publish('cms-pages', page.pk)
        public = APIClient().get('/api/v1/pages/privacy/')
        self.assertEqual(public.status_code, 200)
        self.assertEqual(public.data['body'], '<p>We keep your data safe.</p>')

    def test_an_address_already_in_use_is_refused(self):
        self.client_.post('/api/v1/admin/content/pages/', {'title': 'Terms', 'slug': 'terms'}, format='json')
        again = self.client_.post('/api/v1/admin/content/pages/', {'title': 'Terms again', 'slug': 'terms'}, format='json')
        self.assertEqual(again.status_code, 400)
        self.assertIn('slug', again.data)

    def test_destinations_are_added_listed_and_safely_deleted(self):
        res = self.client_.post('/api/v1/admin/content/destinations/', {'title': 'Test Hill Fort'}, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        place = Destination.objects.get(pk=res.data['id'])
        self.assertEqual(place.slug, 'test-hill-fort')
        cards = self.client_.get('/api/v1/admin/content/destinations/?search=hill fort').data['results']
        self.assertEqual([c['title'] for c in cards], ['Test Hill Fort'])
        self._publish('destinations', place.pk)
        self.assertEqual(self.client_.delete(overview(place.pk, 'destinations')).status_code, 409)

    def test_unknown_kind_is_404(self):
        self.assertEqual(self.client_.get('/api/v1/admin/content/recipes/').status_code, 404)


class CleanHtmlTests(SimpleTestCase):
    def test_plain_text_becomes_paragraphs(self):
        self.assertEqual(clean_html('First line\nsame para\n\nSecond para & co'),
                         '<p>First line<br>same para</p><p>Second para &amp; co</p>')

    def test_empty_paragraphs_and_unknown_tags_are_dropped(self):
        self.assertEqual(clean_html('<div>Hi <img src="x.png"></div><p><br></p><iframe src="x"></iframe>'), '<p>Hi </p>')

    def test_links_open_safely(self):
        self.assertIn('rel="noopener noreferrer nofollow"', clean_html('<a href="https://x.in">x</a>'))
