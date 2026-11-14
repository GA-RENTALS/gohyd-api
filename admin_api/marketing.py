"""Marketing page: coupons, campaigns, newsletter subscribers and referrals, with the numbers a marketer needs.

GET /admin/marketing/<tab>/?status=…&search=…&page=N[&export=csv]   tab: coupons | campaigns | subscribers | referrals

Creating and editing records goes through the generic resources API (/admin/resources/coupons/ …), so model validation
and the audit log stay in one place. This module only adds the friendly lists and the figures around them.
"""
from django.db.models import Count, DecimalField, F, IntegerField, OuterRef, Q, Sum
from django.http import Http404
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from crm.models import Campaign, CampaignCost, Coupon, CouponRedemption, NewsletterSubscription, ReferralCampaign, ReferralRecord
from tracking.models import ConversionEvent, VisitorSession
from trips.models import EventRegistration

from .listing import correlated_total, csv_response, export_filename, paginate, wants_export
from .overview import ZERO, _can, _iso, _money
from .permissions import StaffOnly
from .views import _access_log, _require_model_permission, _resolve

# tab -> the resource key that guards it
TABS = {'coupons': 'coupons', 'campaigns': 'campaigns', 'subscribers': 'newsletters', 'referrals': 'referral-campaigns'}


def _month_start():
    return timezone.localtime().replace(day=1, hour=0, minute=0, second=0, microsecond=0)


class MarketingListView(APIView):
    permission_classes = [StaffOnly]

    def get(self, request, tab):
        if tab not in TABS:
            raise Http404('Unknown marketing tab.')
        resource = _resolve(TABS[tab])
        _require_model_permission(request, resource, 'view')
        search = request.query_params.get('search', '').strip()
        bucket = request.query_params.get('status', 'all')
        qs, groups, to_rows, columns = getattr(self, f'_{tab}')(search)

        counts = {key: qs.filter(q).count() for key, q in groups.items()}
        counts['all'] = qs.count()
        qs = qs.filter(groups[bucket]) if bucket in groups else qs

        if wants_export(request):
            _access_log(request, resource, purpose=f'marketing {tab} export')
            return csv_response(export_filename(tab), columns, to_rows(list(qs)))
        page, meta = paginate(request, qs)
        _access_log(request, resource, purpose=f'marketing {tab}')
        return Response({**meta, 'counts': counts, 'results': to_rows(list(page.object_list)),
                         'summary': marketing_summary(request), 'can': self._can(request, tab)})

    @staticmethod
    def _can(request, tab):
        key = TABS[tab]
        out = {'create': _can(request, key, 'add'), 'update': _can(request, key, 'change')}
        if tab == 'campaigns':
            out['add_cost'] = _can(request, 'campaign-costs', 'add')
        out['tabs'] = [name for name, resource in TABS.items() if _can(request, resource)]
        return out

    # ---- one builder per tab: (queryset, {bucket: Q}, rows(list) -> dicts, CSV columns) ----

    @staticmethod
    def _coupons(search):
        now = timezone.now()
        qs = with_coupon_usage(Coupon.objects.all()).order_by('-created_at')
        if search:
            qs = qs.filter(code__icontains=search)
        used_up = Q(max_redemptions__isnull=False, uses__gte=F('max_redemptions'))
        expired = Q(valid_until__lt=now) | used_up
        groups = {
            'active': Q(is_active=True) & ~expired & (Q(valid_from__isnull=True) | Q(valid_from__lte=now)),
            'scheduled': Q(is_active=True, valid_from__gt=now) & ~expired,
            'ended': Q(is_active=True) & expired,
            'paused': Q(is_active=False),
        }
        columns = [('Code', 'code'), ('Discount', 'discount_label'), ('Status', 'state'), ('Uses', 'uses'), ('Limit', 'max_redemptions'),
                   ('Discount given', 'discount_total'), ('Valid from', 'valid_from'), ('Valid until', 'valid_until'), ('Trips', 'trips_text')]
        return qs, groups, coupon_rows, columns

    @staticmethod
    def _campaigns(search):
        qs = Campaign.objects.annotate(spend=Sum('costs__amount')).order_by('-created_at')
        if search:
            qs = qs.filter(Q(name__icontains=search) | Q(utm_campaign__icontains=search))
        today = timezone.localdate()
        running = Q(is_active=True) & (Q(starts_on__isnull=True) | Q(starts_on__lte=today)) & (Q(ends_on__isnull=True) | Q(ends_on__gte=today))
        groups = {'running': running, 'other': ~running}
        columns = [('Campaign', 'name'), ('UTM campaign', 'utm_campaign'), ('Starts', 'starts_on'), ('Ends', 'ends_on'), ('Spend', 'spend'),
                   ('Visitors', 'visitors'), ('Bookings', 'bookings'), ('Revenue', 'revenue'), ('Cost per booking', 'cost_per_booking')]
        return qs, groups, campaign_rows, columns

    @staticmethod
    def _subscribers(search):
        qs = NewsletterSubscription.objects.order_by('-consent_at')
        if search:
            qs = qs.filter(email__icontains=search)
        groups = {'subscribed': Q(unsubscribed_at__isnull=True), 'unsubscribed': Q(unsubscribed_at__isnull=False)}
        columns = [('Email', 'email'), ('Subscribed', 'consent_at'), ('Unsubscribed', 'unsubscribed_at')]
        return qs, groups, subscriber_rows, columns

    @staticmethod
    def _referrals(search):
        qs = ReferralCampaign.objects.annotate(
            referrals=Count('records'), rewarded=Count('records', filter=Q(records__rewarded=True))).order_by('-created_at')
        if search:
            qs = qs.filter(name__icontains=search)
        groups = {'active': Q(is_active=True), 'paused': Q(is_active=False)}
        columns = [('Campaign', 'name'), ('Referrer reward', 'referrer_reward'), ('Friend discount', 'referee_discount'),
                   ('Referrals', 'referrals'), ('Rewarded', 'rewarded'), ('Rewards owed', 'rewards_owed')]
        return qs, groups, referral_rows, columns


def with_coupon_usage(qs):
    """uses / discount_total across trip checkouts and active event bookings (the same count the coupon limit uses)."""
    money = DecimalField(max_digits=12, decimal_places=2)
    trips = CouponRedemption.objects.filter(coupon=OuterRef('pk'))
    events = EventRegistration.objects.filter(coupon=OuterRef('pk')).exclude(status__in=['CANCELLED', 'EXPIRED'])
    return qs.annotate(
        uses=correlated_total(trips, 'COUNT', 'id', IntegerField()) + correlated_total(events, 'COUNT', 'id', IntegerField()),
        discount_total=(correlated_total(trips, 'SUM', 'discount', money)
                        + correlated_total(events, 'SUM', 'discount_amount', money)),
    )


# ---------- rows ----------

def coupon_state(coupon, now):
    if not coupon.is_active:
        return 'paused'
    if (coupon.valid_until and coupon.valid_until < now) or (coupon.max_redemptions is not None and coupon.uses >= coupon.max_redemptions):
        return 'ended'
    if coupon.valid_from and coupon.valid_from > now:
        return 'scheduled'
    return 'active'


def discount_label(coupon):
    if coupon.percent_basis_points:
        percent = coupon.percent_basis_points / 100
        return f'{percent:g}% off'
    if coupon.fixed_amount:
        return f'₹{coupon.fixed_amount:,.0f} off'
    return '—'


def _scope_names(coupons):
    """{coupon id: names of the trips and events it is limited to} (empty = works on everything)."""
    names = {c.pk: [] for c in coupons}
    for through, field in ((Coupon.trips.through, 'trip'), (Coupon.events.through, 'event')):
        for link in through.objects.filter(coupon_id__in=names).select_related(field):
            names[link.coupon_id].append(getattr(link, field).slug.replace('-', ' ').title())
    return names


def coupon_rows(coupons):
    now = timezone.now()
    scope = _scope_names(coupons)
    return [{
        'id': str(c.pk), 'code': c.code, 'discount_label': discount_label(c),
        'percent': c.percent_basis_points / 100 if c.percent_basis_points else None,
        'fixed_amount': _money(c.fixed_amount) if c.fixed_amount else None,
        'state': coupon_state(c, now), 'is_active': c.is_active,
        'uses': c.uses, 'max_redemptions': c.max_redemptions, 'per_user_limit': c.per_user_limit,
        'discount_total': _money(c.discount_total or ZERO),
        'valid_from': _iso(c.valid_from), 'valid_until': _iso(c.valid_until),
        'trips': scope[c.pk], 'trips_text': ', '.join(scope[c.pk]) or 'All trips and events',
    } for c in coupons]


def campaign_rows(campaigns):
    rows = []
    for c in campaigns:
        visitors, bookings, revenue = attribution(c)
        spend = c.spend or ZERO
        rows.append({
            'id': str(c.pk), 'name': c.name, 'utm_campaign': c.utm_campaign, 'is_active': c.is_active,
            'starts_on': c.starts_on.isoformat() if c.starts_on else None, 'ends_on': c.ends_on.isoformat() if c.ends_on else None,
            'spend': _money(spend), 'visitors': visitors, 'bookings': bookings, 'revenue': _money(revenue),
            'cost_per_booking': _money(spend / bookings) if bookings and spend else None,
        })
    return rows


def attribution(campaign):
    """(visitors, bookings, revenue) for visitors who arrived with this campaign's utm_campaign tag.

    A visitor counts once however many sessions they had; a booking counts once however many tagged sessions led to it.
    """
    if not campaign.utm_campaign:
        return 0, 0, ZERO
    sessions = VisitorSession.objects.filter(utm_campaign__iexact=campaign.utm_campaign)
    if campaign.starts_on:
        sessions = sessions.filter(started_at__date__gte=campaign.starts_on)
    if campaign.ends_on:
        sessions = sessions.filter(started_at__date__lte=campaign.ends_on)
    visitor_ids = sessions.values('visitor_id').distinct()
    conversions = ConversionEvent.objects.filter(kind='booking', visitor_id__in=visitor_ids).aggregate(n=Count('id'), t=Sum('value'))
    return visitor_ids.count(), conversions['n'], conversions['t'] or ZERO


def subscriber_rows(subscriptions):
    return [{'id': str(s.pk), 'email': s.email, 'consent_at': _iso(s.consent_at), 'unsubscribed_at': _iso(s.unsubscribed_at),
             'subscribed': s.unsubscribed_at is None} for s in subscriptions]


def referral_rows(campaigns):
    return [{
        'id': str(c.pk), 'name': c.name, 'is_active': c.is_active,
        'referrer_reward': _money(c.referrer_reward), 'referee_discount': _money(c.referee_discount),
        'referrals': c.referrals, 'rewarded': c.rewarded, 'rewards_owed': _money(c.referrer_reward * (c.referrals - c.rewarded)),
    } for c in campaigns]


# ---------- summary ----------

def marketing_summary(request):
    """Headline numbers for the tabs the staff member can open."""
    month_start = _month_start()
    out = {}
    if _can(request, 'coupons'):
        now = timezone.now()
        live = Coupon.objects.filter(is_active=True).filter(Q(valid_until__isnull=True) | Q(valid_until__gte=now))
        trips = CouponRedemption.objects.filter(created_at__gte=month_start).aggregate(n=Count('id'), t=Sum('discount'))
        events = (EventRegistration.objects.filter(coupon__isnull=False, created_at__gte=month_start)
                  .exclude(status__in=['CANCELLED', 'EXPIRED']).aggregate(n=Count('id'), t=Sum('discount_amount')))
        out['coupons'] = {'live': live.count(), 'uses_month': trips['n'] + events['n'],
                          'discount_month': _money((trips['t'] or ZERO) + (events['t'] or ZERO))}
    if _can(request, 'campaigns'):
        today = timezone.localdate()
        running = Campaign.objects.filter(is_active=True).filter(Q(starts_on__isnull=True) | Q(starts_on__lte=today)).filter(
            Q(ends_on__isnull=True) | Q(ends_on__gte=today))
        spend = CampaignCost.objects.filter(spent_on__gte=month_start.date()).aggregate(t=Sum('amount'))['t'] or ZERO
        out['campaigns'] = {'running': running.count(), 'spend_month': _money(spend)}
    if _can(request, 'newsletters'):
        subscribed = NewsletterSubscription.objects.filter(unsubscribed_at__isnull=True)
        out['subscribers'] = {'total': subscribed.count(), 'new_month': subscribed.filter(consent_at__gte=month_start).count()}
    if _can(request, 'referral-campaigns'):
        out['referrals'] = {'month': ReferralRecord.objects.filter(created_at__gte=month_start).count(),
                            'unrewarded': ReferralRecord.objects.filter(rewarded=False).count()}
    return out
