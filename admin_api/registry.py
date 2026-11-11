"""Allow-listed resources exposed to the staff dashboard."""
from dataclasses import dataclass, field

from django.contrib.auth.models import Group

from accounts.models import CustomerProfile, LoginHistory, ResourceAssignment, Team, User
from notifications.models import (BackupExecutionLog, IntegrationConfiguration, IntegrationExecutionLog, IntegrationHealthStatus,
                                   IntegrationProvider, NotificationDeliveryLog, NotificationFailure, NotificationJob,
                                   NotificationPreference, NotificationTemplate, NotificationTranslation, SystemHealthLog,
                                   WebhookLog, WebhookRecord)
from tenancy.models import TenantDomain, TenantMembership
from bookings.models import (Booking, BookingItem, BookingParticipant, BookingSeatAllocation, BookingStatusHistory,
                             BookingCancellation, BookingModification, BookingConfirmation, Cart, CartItem,
                             CheckoutItem, CheckoutOrder, ParticipantPickupAssignment)
from content.models import (Blog, BlogCategory, BlogTag, BlogTranslation, CmsPage, CmsPageTranslation,
                            Destination, DestinationActivity, DestinationCategory, DestinationMedia,
                            DestinationTranslation, FAQ, Gallery, GalleryItem, MediaAsset, MediaFolder,
                            PublishingSchedule, SeoMetadata, Testimonial)
from core.models import (AuditLog, DataAccessLog, DataRequest, OutboxEvent, SecurityEvent, Setting)
from crm.models import Reward
from crm.models import (Campaign, CampaignChannel, CampaignCost, CampaignCreative, Complaint, CorporateEnquiry,
                        CorporateQuotation, Coupon, CouponRedemption, CustomerInteraction, CustomerMembership,
                        CustomerSegment, Enquiry, EnquiryAssignment, EnquiryFollowup, EnquirySource,
                        LoyaltyAccount, LoyaltyTransaction, MembershipBenefit, MembershipPlan,
                        MembershipRenewal, MembershipTransaction, NewsletterSubscription, ReferralCampaign,
                        ReferralRecord, Review, SegmentMember, SupportAssignment, SupportMessage, SupportTicket)
from operations.models import (Driver, EmergencyContact, EmergencyEscalation, IncidentAction, IncidentReport,
                               ParticipantWaiverAcceptance, PickupLocation, SafetyChecklist, SafetyWaiver,
                               TripCompletionReport, TripDriverAssignment, TripVehicleAssignment, Vehicle,
                               VehicleDocument, Vendor, VendorContact, VendorContract, VendorDocument,
                               VendorPricing, VendorService, VendorTripAssignment)
from payments.models import InvoiceItem, TripExpense
from payments.models import (BusinessEntity, CreditNote, Expense, ExpenseCategory, FinancialAdjustment,
                            FinancialPeriod, GstConfiguration, Invoice, Payment, PaymentAllocation,
                            PaymentGatewayEvent, PaymentReconciliationRecord, PaymentTransaction,
                            PaymentVerification, Refund, RefundTransaction, Settlement, VendorInvoice,
                            VendorPayment)
from tracking.models import (ConversionEvent, TrackingConsent, Visitor, VisitorEvent, VisitorSession)
from tracking.models import (AnalyticsDailySummary, AnalyticsEventDefinition, CustomerMetric,
                             FinancialPerformanceSummary, KpiDefinition, MarketingAttributionSummary,
                             OperationalPerformanceSummary, ReportDefinition, ReportExecutionHistory,
                             ScheduledReport, TripPerformanceSummary)
from trips.models import (TripAssignment, TripCategoryLink, TripExclusion, TripStatusHistory, TripThingToBring)
from trips.models import (Event, EventAttendance, EventExclusion, EventInclusion, EventItinerary,
                          EventItineraryItem, EventParticipant, EventRegistration, EventSchedule,
                          EventThingToBring, EventTranslation, Trip, TripCategory, TripDestination, TripInclusion, TripItinerary,
                          TripItineraryItem, TripMedia, TripPickupPoint, TripPolicy, TripPricingRule,
                          TripSchedule, TripTranslation)


@dataclass(frozen=True)
class Resource:
    key: str
    module: str
    label: str
    model: type
    mode: str = 'full'  # full | read | create | update | create_update
    fields: tuple[str, ...] = ()
    read_only_fields: tuple[str, ...] = ()
    search_fields: tuple[str, ...] = ()
    ordering_fields: tuple[str, ...] = ()
    personal_data: bool = False
    queryset_filter: dict = field(default_factory=dict)
    exclude_fields: tuple[str, ...] = ()


def _r(key, module, label, model, **kwargs):
    return Resource(key, module, label, model, **kwargs)


RESOURCES = {
    r.key: r for r in [
        # Trips and destinations
        _r('trips', 'trips', 'Trips', Trip, mode='create_update', search_fields=('slug',), ordering_fields=('created_at', 'sort_order', 'status'), read_only_fields=('status', 'publish_at', 'published_at')),
        _r('trip-schedules', 'trips', 'Schedules', TripSchedule, search_fields=('trip__slug',), ordering_fields=('starts_at', 'created_at')),
        _r('trip-categories', 'trips', 'Categories', TripCategory, search_fields=('name', 'slug'), ordering_fields=('sort_order', 'name')),
        _r('trip-translations', 'trips', 'Trip translations', TripTranslation, search_fields=('title', 'language'), read_only_fields=('status', 'reviewed_by', 'approved_at')),
        _r('trip-itineraries', 'trips', 'Itineraries', TripItinerary, search_fields=('trip__slug',)),
        _r('trip-itinerary-items', 'trips', 'Itinerary items', TripItineraryItem),
        _r('trip-pickup-points', 'trips', 'Pickup points', TripPickupPoint, search_fields=('name',)),
        _r('trip-pricing-rules', 'trips', 'Pricing rules', TripPricingRule),
        _r('trip-policies', 'trips', 'Policies', TripPolicy),
        _r('trip-media', 'trips', 'Trip media', TripMedia),
        _r('trip-inclusions', 'trips', 'Inclusions', TripInclusion),
        _r('trip-things-to-bring', 'trips', 'Things to bring', TripThingToBring),
        _r('trip-destinations', 'trips', 'Trip destinations', TripDestination),
        _r('events', 'trips', 'Events', Event, search_fields=('slug',), read_only_fields=('status', 'publish_at', 'published_at')),
        _r('event-schedules', 'trips', 'Event schedules', EventSchedule),
        _r('event-translations', 'trips', 'Event translations', EventTranslation, read_only_fields=('status', 'reviewed_by', 'approved_at')),
        _r('event-itineraries', 'trips', 'Event itineraries', EventItinerary, search_fields=('event__slug',)),
        _r('event-itinerary-items', 'trips', 'Event itinerary items', EventItineraryItem),
        _r('event-things-to-bring', 'trips', 'Event things to bring', EventThingToBring),
        _r('event-inclusions', 'trips', 'Event inclusions', EventInclusion),
        _r('event-exclusions', 'trips', 'Event exclusions', EventExclusion),
        _r('event-registrations', 'bookings', 'Event registrations', EventRegistration, mode='read', personal_data=True),
        _r('event-participants', 'participants', 'Event participants', EventParticipant, mode='update', personal_data=True),
        _r('event-attendance', 'participants', 'Event attendance', EventAttendance, mode='update', personal_data=True),
        _r('destinations', 'destinations', 'Destinations', Destination, mode='update', search_fields=('slug', 'region'), ordering_fields=('sort_order', 'created_at'), read_only_fields=('status', 'publish_at', 'published_at')),
        _r('destination-categories', 'destinations', 'Destination categories', DestinationCategory, search_fields=('name', 'slug')),
        _r('destination-translations', 'destinations', 'Translations', DestinationTranslation, search_fields=('title', 'language'), read_only_fields=('status', 'reviewed_by', 'approved_at')),
        _r('destination-activities', 'destinations', 'Activities', DestinationActivity, search_fields=('name',)),
        _r('destination-media', 'destinations', 'Destination media', DestinationMedia),
        # Booking lifecycle: order/payment snapshots are intentionally read-only.
        _r('carts', 'checkout', 'Carts', Cart, mode='read', personal_data=True),
        _r('cart-items', 'checkout', 'Cart items', CartItem, mode='read'),
        _r('checkouts', 'checkout', 'Checkouts', CheckoutOrder, mode='read', search_fields=('reference', 'user__phone_number'), personal_data=True),
        _r('checkout-items', 'checkout', 'Checkout items', CheckoutItem, mode='read'),
        _r('bookings', 'bookings', 'Bookings', Booking, mode='read', search_fields=('reference', 'primary_booker__phone_number'), personal_data=True),
        _r('booking-items', 'bookings', 'Booking items', BookingItem, mode='read'),
        _r('participants', 'participants', 'Participants', BookingParticipant, mode='update', search_fields=('full_name', 'phone'), personal_data=True, exclude_fields=('medical_notes',)),
        _r('participant-pickups', 'participants', 'Pickup assignments', ParticipantPickupAssignment, mode='update', personal_data=True),
        _r('booking-seats', 'bookings', 'Seat allocations', BookingSeatAllocation, mode='read'),
        _r('booking-history', 'bookings', 'Booking history', BookingStatusHistory, mode='read'),
        _r('booking-cancellations', 'bookings', 'Cancellations', BookingCancellation, mode='read'),
        _r('booking-modifications', 'bookings', 'Modifications', BookingModification, mode='read'),
        _r('booking-confirmations', 'bookings', 'Confirmations', BookingConfirmation, mode='read'),
        # Payments and finance. Transaction/snapshot rows are never edited in place.
        _r('payments', 'payments', 'Payments', Payment, mode='read', search_fields=('manual_reference', 'payer__phone_number'), personal_data=True, exclude_fields=('gateway_order_id', 'gateway_payment_id', 'idempotency_key')),
        _r('payment-allocations', 'payments', 'Payment allocations', PaymentAllocation, mode='read'),
        _r('payment-transactions', 'payments', 'Payment history', PaymentTransaction, mode='read', exclude_fields=('raw',)),
        _r('payment-verifications', 'payments', 'Payment verifications', PaymentVerification, mode='read', exclude_fields=('proof',)),
        _r('refunds', 'payments', 'Refunds', Refund, mode='read'),
        _r('refund-transactions', 'payments', 'Refund transactions', RefundTransaction, mode='read', exclude_fields=('raw',)),
        _r('gateway-events', 'audit', 'Gateway events', PaymentGatewayEvent, mode='read', exclude_fields=('payload',)),
        _r('reconciliations', 'finance', 'Reconciliation', PaymentReconciliationRecord, mode='read'),
        _r('business-entities', 'finance', 'Business entities', BusinessEntity, search_fields=('legal_name', 'gstin')),
        _r('gst-configurations', 'finance', 'GST configurations', GstConfiguration, mode='create', search_fields=('name',), ordering_fields=('effective_from',)),
        _r('invoices', 'finance', 'Invoices', Invoice, mode='read'),
        _r('credit-notes', 'finance', 'Credit notes', CreditNote, mode='read'),
        _r('expense-categories', 'finance', 'Expense categories', ExpenseCategory, search_fields=('name',)),
        _r('expenses', 'finance', 'Expenses', Expense, search_fields=('description',), personal_data=True),
        _r('vendor-invoices', 'finance', 'Vendor invoices', VendorInvoice, search_fields=('number',)),
        _r('vendor-payments', 'finance', 'Vendor payments', VendorPayment, mode='read'),
        _r('settlements', 'finance', 'Settlements', Settlement, mode='read'),
        _r('financial-periods', 'finance', 'Financial periods', FinancialPeriod),
        _r('financial-adjustments', 'finance', 'Financial adjustments', FinancialAdjustment, mode='create'),
        # Customers, access control, vendors and field operations
        _r('customers', 'customers', 'Customers', User, mode='update', fields=('id', 'phone_number', 'full_name', 'email', 'preferred_language', 'date_joined', 'is_active'), read_only_fields=('id', 'phone_number', 'date_joined', 'is_active'), search_fields=('phone_number', 'full_name', 'email'), personal_data=True, queryset_filter={'kind': User.Kind.CUSTOMER}, ordering_fields=('date_joined', 'full_name')),
        _r('customer-profiles', 'customers', 'Customer profiles', CustomerProfile, mode='update', personal_data=True),
        _r('teams', 'permissions', 'Teams', Team, search_fields=('name',)),
        _r('staff-groups', 'permissions', 'Permission groups', Group, search_fields=('name',)),
        _r('resource-assignments', 'permissions', 'Resource assignments', ResourceAssignment, personal_data=True),
        _r('vendors', 'vendors', 'Vendors', Vendor, search_fields=('name', 'gstin')),
        _r('vendor-contacts', 'vendors', 'Vendor contacts', VendorContact, personal_data=True),
        _r('vendor-services', 'vendors', 'Vendor services', VendorService),
        _r('vendor-contracts', 'vendors', 'Vendor contracts', VendorContract),
        _r('vendor-pricing', 'vendors', 'Vendor pricing', VendorPricing),
        _r('vendor-documents', 'vendors', 'Vendor documents', VendorDocument),
        _r('vendor-trip-assignments', 'vendors', 'Trip assignments', VendorTripAssignment),
        _r('vehicles', 'logistics', 'Vehicles', Vehicle),
        _r('vehicle-documents', 'logistics', 'Vehicle documents', VehicleDocument),
        _r('drivers', 'logistics', 'Drivers', Driver, personal_data=True),
        _r('trip-vehicles', 'logistics', 'Vehicle assignments', TripVehicleAssignment),
        _r('trip-drivers', 'logistics', 'Driver assignments', TripDriverAssignment),
        _r('pickup-locations', 'logistics', 'Pickup locations', PickupLocation),
        _r('safety-checklists', 'logistics', 'Safety checklists', SafetyChecklist),
        _r('safety-waivers', 'logistics', 'Safety waivers', SafetyWaiver),
        _r('waiver-acceptances', 'participants', 'Waiver acceptances', ParticipantWaiverAcceptance, mode='read', personal_data=True),
        _r('emergency-contacts', 'participants', 'Emergency contacts', EmergencyContact, mode='update', personal_data=True),
        _r('incidents', 'logistics', 'Incidents', IncidentReport, personal_data=True),
        _r('incident-actions', 'logistics', 'Incident actions', IncidentAction),
        _r('emergency-escalations', 'logistics', 'Emergency escalations', EmergencyEscalation),
        _r('trip-completion-reports', 'logistics', 'Completion reports', TripCompletionReport),
        # CRM, marketing and memberships
        _r('enquiries', 'crm', 'Enquiries', Enquiry, search_fields=('name', 'phone', 'email', 'message', 'event__slug', 'event_schedule__event__slug'), personal_data=True),
        _r('enquiry-sources', 'crm', 'Enquiry sources', EnquirySource),
        _r('enquiry-assignments', 'crm', 'Enquiry assignments', EnquiryAssignment, personal_data=True),
        _r('enquiry-followups', 'crm', 'Follow-ups', EnquiryFollowup, personal_data=True),
        _r('support-tickets', 'crm', 'Support tickets', SupportTicket, search_fields=('subject',), personal_data=True),
        _r('support-messages', 'crm', 'Support messages', SupportMessage, personal_data=True),
        _r('support-assignments', 'crm', 'Support assignments', SupportAssignment, personal_data=True),
        _r('complaints', 'crm', 'Complaints', Complaint, personal_data=True),
        _r('customer-interactions', 'crm', 'Customer interactions', CustomerInteraction, personal_data=True),
        _r('corporate-enquiries', 'crm', 'Corporate enquiries', CorporateEnquiry, personal_data=True),
        _r('corporate-quotations', 'crm', 'Corporate quotations', CorporateQuotation),
        _r('campaigns', 'marketing', 'Campaigns', Campaign, search_fields=('name', 'utm_campaign')),
        _r('campaign-channels', 'marketing', 'Campaign channels', CampaignChannel),
        _r('campaign-costs', 'marketing', 'Campaign costs', CampaignCost),
        _r('campaign-creatives', 'marketing', 'Campaign creatives', CampaignCreative),
        _r('coupons', 'marketing', 'Coupons', Coupon, search_fields=('code',)),
        _r('coupon-redemptions', 'marketing', 'Coupon redemptions', CouponRedemption, mode='read', personal_data=True),
        _r('newsletters', 'marketing', 'Newsletter subscribers', NewsletterSubscription, personal_data=True),
        _r('customer-segments', 'marketing', 'Customer segments', CustomerSegment),
        _r('segment-members', 'marketing', 'Segment members', SegmentMember, personal_data=True),
        _r('referral-campaigns', 'marketing', 'Referral campaigns', ReferralCampaign),
        _r('referrals', 'marketing', 'Referrals', ReferralRecord, personal_data=True),
        _r('membership-plans', 'memberships', 'Plans', MembershipPlan, search_fields=('name',)),
        _r('membership-benefits', 'memberships', 'Benefits', MembershipBenefit),
        _r('memberships', 'memberships', 'Memberships', CustomerMembership, mode='read', personal_data=True),
        _r('membership-transactions', 'memberships', 'Transactions', MembershipTransaction, mode='read'),
        _r('membership-renewals', 'memberships', 'Renewals', MembershipRenewal, mode='read'),
        _r('loyalty-accounts', 'memberships', 'Loyalty accounts', LoyaltyAccount, mode='read', personal_data=True),
        _r('loyalty-transactions', 'memberships', 'Loyalty transactions', LoyaltyTransaction, mode='read'),
        _r('reviews', 'crm', 'Reviews', Review, search_fields=('body',), personal_data=True),
        # CMS and publishing
        _r('cms-pages', 'cms', 'Pages', CmsPage, mode='update', search_fields=('slug', 'kind'), read_only_fields=('status', 'publish_at', 'published_at')),
        _r('cms-translations', 'cms', 'Page translations', CmsPageTranslation, search_fields=('title', 'language'), read_only_fields=('status', 'reviewed_by', 'approved_at')),
        _r('blogs', 'cms', 'Blogs', Blog, mode='update', search_fields=('slug',), read_only_fields=('status', 'publish_at', 'published_at')),
        _r('blog-translations', 'cms', 'Blog translations', BlogTranslation, search_fields=('title', 'language'), read_only_fields=('status', 'reviewed_by', 'approved_at')),
        _r('blog-categories', 'cms', 'Blog categories', BlogCategory, search_fields=('name', 'slug')),
        _r('blog-tags', 'cms', 'Blog tags', BlogTag, search_fields=('name', 'slug')),
        _r('faqs', 'cms', 'FAQs', FAQ, search_fields=('question_en',)),
        _r('testimonials', 'cms', 'Testimonials', Testimonial),
        _r('media-assets', 'cms', 'Media assets', MediaAsset, search_fields=('alt_text', 'credit')),
        _r('media-folders', 'cms', 'Media folders', MediaFolder),
        _r('galleries', 'cms', 'Galleries', Gallery),
        _r('gallery-items', 'cms', 'Gallery items', GalleryItem),
        _r('seo-metadata', 'cms', 'SEO metadata', SeoMetadata),
        _r('publishing-schedules', 'cms', 'Publishing schedules', PublishingSchedule),
        # Analytics, audit, privacy and runtime health
        _r('analytics-daily', 'analytics', 'Daily analytics', AnalyticsDailySummary, mode='read'),
        _r('trip-performance', 'analytics', 'Trip performance', TripPerformanceSummary, mode='read'),
        _r('financial-performance', 'analytics', 'Financial performance', FinancialPerformanceSummary, mode='read'),
        _r('operational-performance', 'analytics', 'Operational performance', OperationalPerformanceSummary, mode='read'),
        _r('marketing-attribution', 'analytics', 'Marketing attribution', MarketingAttributionSummary, mode='read'),
        _r('customer-metrics', 'analytics', 'Customer metrics', CustomerMetric, mode='read', personal_data=True),
        _r('kpi-definitions', 'analytics', 'KPI definitions', KpiDefinition),
        _r('event-definitions', 'analytics', 'Event definitions', AnalyticsEventDefinition),
        _r('report-definitions', 'analytics', 'Report definitions', ReportDefinition),
        _r('scheduled-reports', 'analytics', 'Scheduled reports', ScheduledReport),
        _r('report-executions', 'analytics', 'Report executions', ReportExecutionHistory, mode='read'),
        _r('trip-exclusions', 'trips', 'Trip exclusions', TripExclusion),
        _r('trip-assignments', 'trips', 'Trip staff assignments', TripAssignment),
        _r('trip-category-links', 'trips', 'Trip categories', TripCategoryLink),
        _r('trip-status-history', 'trips', 'Trip status history', TripStatusHistory, mode='read'),
        _r('invoice-items', 'finance', 'Invoice items', InvoiceItem, mode='read'),
        _r('trip-expenses', 'finance', 'Trip expenses', TripExpense),
        _r('rewards', 'memberships', 'Loyalty rewards', Reward, search_fields=('name',)),
        _r('notification-templates', 'notifications', 'Templates', NotificationTemplate, search_fields=('event', 'provider_template_name')),
        _r('notification-translations', 'notifications', 'Template translations', NotificationTranslation, search_fields=('subject',)),
        _r('notification-preferences', 'notifications', 'Customer preferences', NotificationPreference, mode='read', personal_data=True),
        _r('notification-jobs', 'notifications', 'Notification queue', NotificationJob, mode='read', personal_data=True, exclude_fields=('context',)),
        _r('notification-deliveries', 'notifications', 'Delivery log', NotificationDeliveryLog, mode='read'),
        _r('notification-failures', 'notifications', 'Failures', NotificationFailure, mode='read'),
        _r('integration-providers', 'system', 'Integrations', IntegrationProvider, mode='read', search_fields=('name', 'key')),
        _r('integration-configs', 'system', 'Integration settings', IntegrationConfiguration, mode='read'),
        _r('integration-runs', 'system', 'Integration runs', IntegrationExecutionLog, mode='read'),
        _r('integration-health', 'system', 'Integration health', IntegrationHealthStatus, mode='read'),
        _r('webhook-records', 'audit', 'Webhooks received', WebhookRecord, mode='read', exclude_fields=('payload',)),
        _r('webhook-logs', 'audit', 'Webhook log', WebhookLog, mode='read'),
        _r('system-health', 'system', 'System health', SystemHealthLog, mode='read'),
        _r('backups', 'system', 'Backups', BackupExecutionLog, mode='read'),
        _r('login-history', 'audit', 'Login history', LoginHistory, mode='read', personal_data=True, search_fields=('phone_number',)),
        _r('staff-memberships', 'permissions', 'Operator memberships', TenantMembership, mode='read', personal_data=True),
        _r('tenant-domains', 'permissions', 'Domains', TenantDomain, mode='read', search_fields=('hostname',)),
        _r('visitors', 'analytics', 'Visitors', Visitor, mode='read', personal_data=True),
        _r('visitor-sessions', 'analytics', 'Visitor sessions', VisitorSession, mode='read', personal_data=True),
        _r('visitor-events', 'analytics', 'Visitor events', VisitorEvent, mode='read', personal_data=True, exclude_fields=('properties',)),
        _r('tracking-consents', 'analytics', 'Tracking consents', TrackingConsent, mode='read', personal_data=True, exclude_fields=('ip',)),
        _r('conversions', 'analytics', 'Conversions', ConversionEvent, mode='read', personal_data=True),
        _r('audit-logs', 'audit', 'Audit log', AuditLog, mode='read', exclude_fields=('before', 'after')),
        _r('data-access-logs', 'audit', 'Data access log', DataAccessLog, mode='read'),
        _r('security-events', 'audit', 'Security events', SecurityEvent, mode='read', exclude_fields=('detail',)),
        _r('data-requests', 'audit', 'Privacy requests', DataRequest, mode='update', personal_data=True, read_only_fields=('user', 'kind', 'created_at')),
        _r('settings', 'system', 'Business settings', Setting, mode='update', fields=('key', 'value', 'description'), read_only_fields=('key',)),
        _r('outbox-events', 'system', 'Outbox events', OutboxEvent, mode='read', exclude_fields=('payload', 'last_error')),
    ]
}

MODULE_LABELS = {
    'dashboard': 'Overview', 'trips': 'Trips', 'destinations': 'Destinations', 'bookings': 'Bookings',
    'checkout': 'Checkout', 'payments': 'Payments', 'finance': 'Finance', 'customers': 'Customers',
    'participants': 'Participants', 'vendors': 'Vendors', 'logistics': 'Logistics', 'crm': 'CRM',
    'cms': 'CMS', 'notifications': 'Notifications', 'memberships': 'Memberships', 'marketing': 'Marketing', 'analytics': 'Analytics',
    'permissions': 'Permissions', 'audit': 'Audit logs', 'system': 'System',
}


def get_resource(key):
    return RESOURCES.get(key)


def module_resource_keys(module):
    return [r.key for r in RESOURCES.values() if r.module == module]
