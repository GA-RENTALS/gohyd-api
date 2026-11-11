"""CRM, support, corporate, marketing, memberships, loyalty (sections 13.7, 13.11, 13.12)."""
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from core.models import TenantBound, Timestamped, UUIDModel

MONEY = dict(max_digits=12, decimal_places=2)


# ---------- CRM & support ----------
class EnquirySource(TenantBound):
    name = models.CharField(max_length=60, unique=True)   # website, whatsapp, instagram, referral, corporate

    class Meta:
        db_table = 'enquiry_sources'

    def __str__(self):
        return self.name


class Enquiry(UUIDModel, Timestamped):
    class Status(models.TextChoices):
        NEW = 'NEW'
        CONTACTED = 'CONTACTED'
        QUALIFIED = 'QUALIFIED'
        CONVERTED = 'CONVERTED'
        LOST = 'LOST'

    name = models.CharField(max_length=150)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    message = models.TextField(blank=True)
    trip = models.ForeignKey('trips.Trip', null=True, blank=True, on_delete=models.SET_NULL, related_name='enquiries')
    event = models.ForeignKey('trips.Event', null=True, blank=True, on_delete=models.SET_NULL, related_name='enquiries')
    event_schedule = models.ForeignKey('trips.EventSchedule', null=True, blank=True, on_delete=models.SET_NULL, related_name='enquiries')
    preferred_date = models.DateField(null=True, blank=True)
    group_size = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(30)])
    source = models.ForeignKey(EnquirySource, null=True, blank=True, on_delete=models.SET_NULL, related_name='enquiries')
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.NEW, db_index=True)
    visitor = models.ForeignKey('tracking.Visitor', null=True, blank=True, on_delete=models.SET_NULL, related_name='enquiries')
    consent_to_contact = models.BooleanField(default=False)
    answered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'enquiries'
        ordering = ['-created_at']


class EnquiryAssignment(TenantBound):
    enquiry = models.ForeignKey(Enquiry, on_delete=models.CASCADE, related_name='assignments')
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'enquiry_assignments'


class EnquiryFollowup(TenantBound):
    enquiry = models.ForeignKey(Enquiry, on_delete=models.CASCADE, related_name='followups')
    note = models.TextField()
    due_at = models.DateTimeField(null=True, blank=True)
    done = models.BooleanField(default=False)
    by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'enquiry_followups'


class SupportTicket(UUIDModel, Timestamped):
    class Status(models.TextChoices):
        OPEN = 'OPEN'
        PENDING = 'PENDING'
        RESOLVED = 'RESOLVED'
        CLOSED = 'CLOSED'

    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='tickets')
    booking = models.ForeignKey('bookings.Booking', null=True, blank=True, on_delete=models.SET_NULL, related_name='tickets')
    subject = models.CharField(max_length=200)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN, db_index=True)

    class Meta:
        db_table = 'support_tickets'
        ordering = ['-created_at']


class SupportMessage(TenantBound):
    ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name='messages')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    body = models.TextField()
    is_staff_reply = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'support_messages'


class SupportAssignment(TenantBound):
    ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name='assignments')
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')

    class Meta:
        db_table = 'support_assignments'


class Complaint(UUIDModel, Timestamped):
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='complaints')
    booking = models.ForeignKey('bookings.Booking', null=True, blank=True, on_delete=models.SET_NULL, related_name='complaints')
    description = models.TextField()
    resolution = models.TextField(blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'complaints'


class CustomerInteraction(TenantBound):
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='interactions')
    channel = models.CharField(max_length=20)     # call, whatsapp, email, in_person
    summary = models.TextField()
    by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'customer_interactions'


class CorporateEnquiry(UUIDModel, Timestamped):
    company = models.CharField(max_length=200)
    contact_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    group_size = models.PositiveIntegerField(null=True, blank=True)
    preferred_dates = models.CharField(max_length=200, blank=True)
    brief = models.TextField(blank=True)
    status = models.CharField(max_length=12, default='NEW')

    class Meta:
        db_table = 'corporate_enquiries'


class CorporateQuotation(UUIDModel, Timestamped):
    enquiry = models.ForeignKey(CorporateEnquiry, on_delete=models.CASCADE, related_name='quotations')
    amount = models.DecimalField(**MONEY)
    tax_amount = models.DecimalField(default=0, **MONEY)
    valid_until = models.DateField(null=True, blank=True)
    terms = models.TextField(blank=True)
    status = models.CharField(max_length=12, default='DRAFT')

    class Meta:
        db_table = 'corporate_quotations'


# ---------- Marketing ----------
class Campaign(UUIDModel, Timestamped):
    name = models.CharField(max_length=150)
    utm_campaign = models.CharField(max_length=100, blank=True, db_index=True)
    starts_on = models.DateField(null=True, blank=True)
    ends_on = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'campaigns'

    def __str__(self):
        return self.name


class CampaignChannel(TenantBound):
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='channels')
    channel = models.CharField(max_length=30)    # instagram, google, whatsapp, email, offline
    utm_source = models.CharField(max_length=60, blank=True)
    utm_medium = models.CharField(max_length=60, blank=True)

    class Meta:
        db_table = 'campaign_channels'


class CampaignCost(TenantBound):
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='costs')
    spent_on = models.DateField()
    amount = models.DecimalField(**MONEY)
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = 'campaign_costs'


class CampaignCreative(Timestamped):
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='creatives')
    name = models.CharField(max_length=120)
    asset = models.ForeignKey('content.MediaAsset', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        db_table = 'campaign_creatives'


class Coupon(UUIDModel, Timestamped):
    code = models.CharField(max_length=30, unique=True)
    percent_basis_points = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MaxValueValidator(10000)])
    fixed_amount = models.DecimalField(null=True, blank=True, **MONEY)
    max_redemptions = models.PositiveIntegerField(null=True, blank=True)
    per_user_limit = models.PositiveSmallIntegerField(default=1)
    valid_from = models.DateTimeField(null=True, blank=True)
    valid_until = models.DateTimeField(null=True, blank=True)
    trips = models.ManyToManyField('trips.Trip', blank=True, related_name='coupons')
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'coupons'


class CouponRedemption(UUIDModel):
    coupon = models.ForeignKey(Coupon, on_delete=models.PROTECT, related_name='redemptions')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    checkout = models.ForeignKey('bookings.CheckoutOrder', null=True, on_delete=models.SET_NULL, related_name='+')
    discount = models.DecimalField(**MONEY)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'coupon_redemptions'


class NewsletterSubscription(Timestamped):
    email = models.EmailField(unique=True)
    consent_at = models.DateTimeField()
    unsubscribed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'newsletter_subscriptions'


class CustomerSegment(Timestamped):
    name = models.CharField(max_length=120, unique=True)
    rule = models.JSONField(default=dict, blank=True, help_text='Saved filter definition (e.g. {"min_bookings": 2}).')

    class Meta:
        db_table = 'customer_segments'


class SegmentMember(TenantBound):
    segment = models.ForeignKey(CustomerSegment, on_delete=models.CASCADE, related_name='members')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')

    class Meta:
        db_table = 'segment_members'
        unique_together = ('segment', 'user')


class ReferralCampaign(Timestamped):
    name = models.CharField(max_length=120)
    referrer_reward = models.DecimalField(default=0, **MONEY)
    referee_discount = models.DecimalField(default=0, **MONEY)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'referral_campaigns'


# ---------- Membership & loyalty ----------
class MembershipPlan(Timestamped):
    name = models.CharField(max_length=100)
    price = models.DecimalField(**MONEY)
    duration_days = models.PositiveIntegerField()
    discount_basis_points = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(10000)])
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'membership_plans'

    def __str__(self):
        return self.name


class MembershipBenefit(TenantBound):
    plan = models.ForeignKey(MembershipPlan, on_delete=models.CASCADE, related_name='benefits')
    text = models.CharField(max_length=200)

    class Meta:
        db_table = 'membership_benefits'


class CustomerMembership(UUIDModel, Timestamped):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='memberships')
    plan = models.ForeignKey(MembershipPlan, on_delete=models.PROTECT, related_name='+')
    starts_on = models.DateField()
    expires_on = models.DateField()
    status = models.CharField(max_length=12, default='ACTIVE')

    class Meta:
        db_table = 'customer_memberships'


class MembershipTransaction(UUIDModel):
    membership = models.ForeignKey(CustomerMembership, on_delete=models.PROTECT, related_name='transactions')
    amount = models.DecimalField(**MONEY)
    payment = models.ForeignKey('payments.Payment', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'membership_transactions'


class MembershipRenewal(TenantBound):
    membership = models.ForeignKey(CustomerMembership, on_delete=models.CASCADE, related_name='renewals')
    renewed_on = models.DateField()
    new_expiry = models.DateField()

    class Meta:
        db_table = 'membership_renewals'


class ReferralRecord(UUIDModel):
    campaign = models.ForeignKey(ReferralCampaign, null=True, on_delete=models.SET_NULL, related_name='records')
    referrer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='referrals_made')
    referee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='referred_by_records')
    rewarded = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'referral_records'


class LoyaltyAccount(TenantBound):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='loyalty')
    points = models.IntegerField(default=0)

    class Meta:
        db_table = 'loyalty_accounts'


class LoyaltyTransaction(TenantBound):
    account = models.ForeignKey(LoyaltyAccount, on_delete=models.CASCADE, related_name='transactions')
    points = models.IntegerField()           # signed
    reason = models.CharField(max_length=120)
    booking = models.ForeignKey('bookings.Booking', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'loyalty_transactions'


class Reward(Timestamped):
    name = models.CharField(max_length=120)
    points_cost = models.PositiveIntegerField()
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'rewards'


class Review(UUIDModel, Timestamped):
    """Customer reviews (community & reviews module): only the booker of a completed trip can review; staff moderate."""
    booking = models.OneToOneField('bookings.Booking', on_delete=models.CASCADE, related_name='review')
    rating = models.PositiveSmallIntegerField()
    body = models.TextField(blank=True)
    is_published = models.BooleanField(default=False)

    class Meta:
        db_table = 'reviews'
