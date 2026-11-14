"""Marketing page: coupon rules, coupon states, campaign attribution, subscribers and access."""
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from core.testing import TenantTestCase

from .test_payments import staff_with
from .tests import _AdminFixtures

TAB = '/api/v1/admin/marketing/{}/'
COUPONS = '/api/v1/admin/resources/coupons/'


class CouponRuleTests(_AdminFixtures, TenantTestCase):
    """Coupons are created through the generic resources API; the model rules apply there."""

    def test_code_is_stored_in_capitals(self):
        res = self.client_.post(COUPONS, {'code': ' diwali10 ', 'percent_basis_points': 1000}, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data['code'], 'DIWALI10')

    def test_percent_and_fixed_amount_are_exclusive(self):
        both = self.client_.post(COUPONS, {'code': 'BOTH', 'percent_basis_points': 1000, 'fixed_amount': '200.00'}, format='json')
        neither = self.client_.post(COUPONS, {'code': 'NEITHER'}, format='json')
        self.assertEqual((both.status_code, neither.status_code), (400, 400))
        self.assertIn('percent_basis_points', both.data)

    def test_codes_are_unique_ignoring_case(self):
        self.client_.post(COUPONS, {'code': 'SUMMER', 'fixed_amount': '100.00'}, format='json')
        again = self.client_.post(COUPONS, {'code': 'summer', 'fixed_amount': '100.00'}, format='json')
        self.assertEqual(again.status_code, 400)
        self.assertIn('code', again.data)

    def test_end_must_be_after_start(self):
        now = timezone.now()
        res = self.client_.post(COUPONS, {'code': 'BACKWARDS', 'fixed_amount': '50.00',
                                          'valid_from': now.isoformat(), 'valid_until': (now - timedelta(days=1)).isoformat()}, format='json')
        self.assertEqual(res.status_code, 400)
        self.assertIn('valid_until', res.data)


class MarketingPageTests(_AdminFixtures, TenantTestCase):

    def test_coupons_tab_groups_by_state_and_counts_uses(self):
        from crm.models import Coupon, CouponRedemption
        now = timezone.now()
        live = Coupon.objects.create(code='LIVE', percent_basis_points=1000)
        Coupon.objects.create(code='LATER', fixed_amount=Decimal('100'), valid_from=now + timedelta(days=3))
        Coupon.objects.create(code='OLD', fixed_amount=Decimal('100'), valid_until=now - timedelta(days=1))
        Coupon.objects.create(code='OFF', fixed_amount=Decimal('100'), is_active=False)
        CouponRedemption.objects.create(coupon=live, user=self.customer, discount=Decimal('250.00'))

        res = self.client_.get(TAB.format('coupons'))
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data['counts'], {'active': 1, 'scheduled': 1, 'ended': 1, 'paused': 1, 'all': 4})
        row = next(r for r in res.data['results'] if r['code'] == 'LIVE')
        self.assertEqual((row['state'], row['uses'], row['discount_total'], row['discount_label']), ('active', 1, '250.00', '10% off'))
        self.assertEqual(res.data['summary']['coupons']['uses_month'], 1)
        self.assertEqual([r['code'] for r in self.client_.get(TAB.format('coupons') + '?status=paused').data['results']], ['OFF'])

    def test_used_up_coupon_counts_as_ended(self):
        from crm.models import Coupon, CouponRedemption
        coupon = Coupon.objects.create(code='ONCE', fixed_amount=Decimal('100'), max_redemptions=1)
        CouponRedemption.objects.create(coupon=coupon, user=self.customer, discount=Decimal('100'))
        rows = self.client_.get(TAB.format('coupons') + '?status=ended').data['results']
        self.assertEqual([r['code'] for r in rows], ['ONCE'])

    def test_campaign_attribution_counts_each_visitor_and_booking_once(self):
        from crm.models import Campaign, CampaignCost
        from tracking.models import ConversionEvent, Visitor, VisitorSession
        campaign = Campaign.objects.create(name='Diwali', utm_campaign='diwali')
        CampaignCost.objects.create(campaign=campaign, spent_on=timezone.localdate(), amount=Decimal('1000.00'))
        visitor = Visitor.objects.create()
        VisitorSession.objects.create(visitor=visitor, utm_campaign='diwali')
        VisitorSession.objects.create(visitor=visitor, utm_campaign='Diwali')   # same person, second visit
        VisitorSession.objects.create(visitor=Visitor.objects.create(), utm_campaign='other')
        ConversionEvent.objects.create(visitor=visitor, kind='booking', value=Decimal('500.00'))

        row = self.client_.get(TAB.format('campaigns')).data['results'][0]
        self.assertEqual((row['visitors'], row['bookings'], row['revenue'], row['spend'], row['cost_per_booking']),
                         (1, 1, '500.00', '1000.00', '1000.00'))

    def test_subscribers_export_as_csv(self):
        from crm.models import NewsletterSubscription
        NewsletterSubscription.objects.create(email='a@example.com', consent_at=timezone.now())
        NewsletterSubscription.objects.create(email='b@example.com', consent_at=timezone.now(), unsubscribed_at=timezone.now())
        res = self.client_.get(TAB.format('subscribers') + '?status=subscribed&export=csv')
        self.assertEqual(res.status_code, 200)
        lines = res.content.decode('utf-8-sig').strip().splitlines()
        self.assertEqual(lines[0], 'Email,Subscribed,Unsubscribed')
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[1].startswith('a@example.com'))

    def test_referral_rewards_owed(self):
        from core.testing import make_user
        from crm.models import ReferralCampaign, ReferralRecord
        campaign = ReferralCampaign.objects.create(name='Bring a friend', referrer_reward=Decimal('200'))
        friend = make_user('+919866666666')
        ReferralRecord.objects.create(campaign=campaign, referrer=self.customer, referee=friend)
        row = self.client_.get(TAB.format('referrals')).data['results'][0]
        self.assertEqual((row['referrals'], row['rewarded'], row['rewards_owed']), (1, 0, '200.00'))

    def test_unknown_tab_is_404_and_access_follows_permissions(self):
        self.assertEqual(self.client_.get(TAB.format('nonsense')).status_code, 404)
        _, writer = staff_with('+919877777777', 'view_cmspage')
        self.assertEqual(writer.get(TAB.format('coupons')).status_code, 403)
        _, marketer = staff_with('+919888888888', 'view_coupon')
        res = marketer.get(TAB.format('coupons'))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['can']['tabs'], ['coupons'])
        self.assertFalse(res.data['can']['create'])
        self.assertEqual(set(res.data['summary']), {'coupons'})
