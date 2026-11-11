"""Create (or refresh) the published Box Cricket Community Play Day event, using the approved event-page copy.

Idempotent: re-running updates the same Event (slug `box-cricket-community-play-day`).
Page sections (highlights, format, schedule, things to bring, inclusions, exclusions, rules, FAQs) are only written
when empty, so staff edits survive. Pass --refresh-content to replace them with the approved copy below.

Usage:  python manage.py seed_box_cricket_event [--tenant gohyderabad] [--refresh-content] [--skip-poster]

--skip-poster creates the event without uploading the poster (use it where file storage has no credentials, e.g. a
laptop without AWS keys). The website shows its bundled poster until one is uploaded in Admin → Media and set as
the event's cover / popup banner.
"""
import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from content.models import ContentStatus, MediaAsset
from tenancy.context import tenant_scope
from tenancy.models import Tenant
from trips.models import (Event, EventExclusion, EventFAQ, EventFormatDetail, EventHighlight, EventInclusion,
                          EventItinerary, EventItineraryItem, EventRegistrationType, EventRule, EventSchedule,
                          EventThingToBring, EventTranslation, TripCategory)

SLUG = 'box-cricket-community-play-day'
POSTER = Path(__file__).resolve().parents[2] / 'seed_assets' / 'box-cricket-poster.jpg'
IST = ZoneInfo('Asia/Kolkata')
STARTS_AT = dt.datetime(2026, 11, 14, 19, 0, tzinfo=IST)   # 7:00 PM
ENDS_AT = dt.datetime(2026, 11, 14, 22, 0, tzinfo=IST)     # 10:00 PM
CAPACITY = 15

TRANSLATIONS = {
    'en': {
        'title': 'Box Cricket Community Play Day',
        'summary': 'Three pool-play matches, 10 overs per match, and three hours of cricket and new friends.',
        'headline': 'Play. Connect. Make New Friends.',
        'image_caption': 'A community evening of cricket, friendly competition and new connections.',
        'body': ('<p>Looking for something fun to do, new people to meet and a little friendly competition? Join us for '
                 'the Box Cricket Community Play Day — an evening designed for sports lovers and people who enjoy '
                 'meeting new faces.</p><p>Come alone or bring your friends. Our organisers will manage team formation '
                 'so everyone can participate, enjoy the game and connect with the GoHyderabad community.</p>'),
        'format_note': ('Participants can register individually or with friends. Teams will be formed by the event '
                        'organisers. Match rules will be explained before play begins.'),
        'schedule_note': ('Match sequence and timings may be adjusted by the organiser depending on attendance and '
                          'ground conditions.'),
    },
    'te': {
        'title': 'బాక్స్ క్రికెట్ కమ్యూనిటీ ప్లే డే',
        'summary': 'మూడు పూల్-ప్లే మ్యాచ్‌లు, ఒక్కో మ్యాచ్‌కు 10 ఓవర్లు, మూడు గంటల క్రికెట్ మరియు కొత్త స్నేహాలు.',
        'headline': 'ఆడండి. కలవండి. కొత్త స్నేహితులను చేసుకోండి.',
        'image_caption': 'క్రికెట్, స్నేహపూర్వక పోటీ మరియు కొత్త పరిచయాల సాయంత్రం.',
        'body': ('<p>సరదాగా గడపడానికి, కొత్త వ్యక్తులను కలవడానికి బాక్స్ క్రికెట్ కమ్యూనిటీ ప్లే డేలో చేరండి.</p>'
                 '<p>ఒంటరిగా రండి లేదా స్నేహితులతో రండి. జట్లను నిర్వాహకులు ఏర్పాటు చేస్తారు.</p>'),
        'format_note': 'వ్యక్తిగతంగా లేదా స్నేహితులతో నమోదు చేసుకోవచ్చు. జట్లను నిర్వాహకులు ఏర్పాటు చేస్తారు.',
        'schedule_note': 'హాజరు మరియు గ్రౌండ్ పరిస్థితులను బట్టి సమయాలు మారవచ్చు.',
    },
    'hi': {
        'title': 'बॉक्स क्रिकेट कम्युनिटी प्ले डे',
        'summary': 'तीन पूल-प्ले मैच, हर मैच में 10 ओवर, और तीन घंटे का क्रिकेट व नए दोस्त।',
        'headline': 'खेलें। जुड़ें। नए दोस्त बनाएं।',
        'image_caption': 'क्रिकेट, दोस्ताना मुकाबले और नई मुलाकातों की एक शाम।',
        'body': ('<p>मज़े, नए लोगों से मिलने और दोस्ताना मुकाबले के लिए बॉक्स क्रिकेट कम्युनिटी प्ले डे में शामिल हों।</p>'
                 '<p>अकेले आएं या दोस्तों के साथ। टीमें आयोजक बनाएंगे।</p>'),
        'format_note': 'आप अकेले या दोस्तों के साथ पंजीकरण कर सकते हैं। टीमें आयोजक बनाएंगे।',
        'schedule_note': 'उपस्थिति और मैदान की स्थिति के अनुसार समय बदल सकता है।',
    },
}

HIGHLIGHTS = ['Meet people from the community', 'Organiser-managed teams', 'Friendly match environment',
              'Three pool-play matches']

FORMAT_DETAILS = [   # (label, value) in English; Telugu/Hindi can be added in the admin panel
    ('Game', 'Box Cricket'),
    ('Match format', 'Pool Play'),
    ('Number of matches', '3'),
    ('Overs per match', '10'),
    ('Team formation', 'Organiser-managed'),
    ('Registration', 'Individual & Group'),
]

TIMELINE = [   # (time label, title, detail)
    ('7:00 PM', 'Arrival & check-in', 'Meet the event team and complete check-in.'),
    ('After check-in', 'Team formation & briefing', 'Meet your teammates and understand the match format.'),
    ('Match 1', 'First pool-play match', '10-over match.'),
    ('Match 2', 'Second pool-play match', '10-over match.'),
    ('Match 3', 'Third pool-play match', '10-over match.'),
    ('10:00 PM', 'Event concludes', 'Wrap up and connect with fellow participants.'),
]

THINGS_TO_BRING = ['Comfortable sportswear.', 'Sports shoes suitable for the turf.', 'Personal water bottle.',
                   'Towel and personal essentials.', 'A positive attitude and sports spirit!']
INCLUSIONS = ['Box cricket turf access.', 'Drinking water.', 'Organiser-managed team formation.',
              'Participation in the scheduled pool-play matches.']
EXCLUSIONS = ['Transportation to and from the venue.', 'Food and refreshments.', 'Personal expenses.',
              'Any service not specifically listed under inclusions.']
RULES = ['Arrive on time for check-in and team formation.', 'Follow the instructions of the event organiser.',
         'Respect teammates, opponents and venue staff.', 'Maintain fair play and good sportsmanship.',
         "Follow the venue's safety guidelines.", 'Final match rules will be communicated before the event.']
FAQS = [
    ('Can I register alone?', 'Yes. Individual registrations are welcome. The event organiser will manage team formation.'),
    ('Can I register with friends?', 'Yes. You can submit a group request, subject to the remaining event capacity.'),
    ('Do I need to arrange my own team?', 'No. Teams will be formed by the event organiser.'),
    ('When is my booking confirmed?', 'Your request is not confirmed until the GoHyderabad team verifies availability and sends a confirmation.'),
    ('What if the event is full?', 'You may contact the event team to check whether a waiting list is available.'),
]


class Command(BaseCommand):
    help = 'Create/refresh the published Box Cricket event with its page content, schedule and popup poster.'

    def add_arguments(self, parser):
        parser.add_argument('--tenant', default='gohyderabad')
        parser.add_argument('--refresh-content', action='store_true',
                            help='Replace the page sections with the approved copy, even if staff edited them.')
        parser.add_argument('--skip-poster', action='store_true',
                            help='Do not upload the poster (no file-storage credentials here).')

    def handle(self, *args, **o):
        tenant = Tenant.objects.filter(slug=o['tenant']).first()
        if tenant is None:
            raise CommandError(f"No tenant '{o['tenant']}'.")
        if not POSTER.exists():
            raise CommandError(f'Poster not found at {POSTER}.')
        refresh = o['refresh_content']

        with tenant_scope(tenant.pk):
            category, _ = TripCategory.objects.get_or_create(
                slug='sports', defaults={'name': 'Sports', 'name_te': 'క్రీడలు', 'name_hi': 'खेल'})

            poster = MediaAsset.objects.filter(alt_text='Box Cricket Community Play Day poster').first()
            if poster is None and not o['skip_poster']:
                poster = MediaAsset(kind='image', alt_text='Box Cricket Community Play Day poster', width=1122, height=1402)
                try:
                    with POSTER.open('rb') as fh:
                        poster.file.save('box-cricket-poster.jpg', File(fh), save=False)
                except Exception as exc:   # noqa: BLE001 - storage backends raise many types (boto, OS, network)
                    raise CommandError(
                        f'Could not upload the poster to file storage ({type(exc).__name__}: {exc}). Nothing was saved.\n'
                        'Either add AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY to .env, run this command on the server, '
                        'or re-run with --skip-poster and upload the poster later in Admin → Media.') from exc
                poster.save()

            media = {'cover': poster, 'popup_banner': poster} if poster else {}
            event, created = Event.objects.update_or_create(slug=SLUG, defaults={
                **media,
                'category': category,
                'venue_name': 'KPHB',
                'venue_address': 'KPHB, Hyderabad',
                'show_in_popup': True,
                'popup_order': 0,
                'price': 499,
                'is_featured': True,
                'booking_whatsapp_number': '+91 90593 38727',
                'registration_type': EventRegistrationType.BOTH,
                'max_participants_per_booking': None,   # 15 is total capacity, not a per-booking limit
            })

            for lang, fields in TRANSLATIONS.items():
                EventTranslation.objects.update_or_create(event=event, language=lang, defaults={
                    **fields, 'status': ContentStatus.APPROVED, 'approved_at': timezone.now(),
                })

            schedule = event.schedules.filter(starts_at__date=STARTS_AT.date()).first() or event.schedules.first()
            if schedule is None:
                schedule = EventSchedule(event=event)
            schedule.starts_at, schedule.ends_at = STARTS_AT, ENDS_AT
            schedule.capacity, schedule.is_date_locked, schedule.time_tbd = CAPACITY, True, False
            schedule.save()

            def write(model, rows, build):
                qs = model.objects.filter(event=event)
                if refresh:
                    qs.delete()
                elif qs.exists():
                    return
                model.objects.bulk_create([build(i, row) for i, row in enumerate(rows)])

            def text_row(model):
                return lambda i, text: model(event=event, text_en=text, sort_order=i, tenant=tenant)

            write(EventHighlight, HIGHLIGHTS, text_row(EventHighlight))
            write(EventThingToBring, THINGS_TO_BRING, text_row(EventThingToBring))
            write(EventInclusion, INCLUSIONS, text_row(EventInclusion))
            write(EventExclusion, EXCLUSIONS, text_row(EventExclusion))
            write(EventRule, RULES, text_row(EventRule))
            write(EventFormatDetail, FORMAT_DETAILS, lambda i, row: EventFormatDetail(
                event=event, label_en=row[0], value_en=row[1], sort_order=i, tenant=tenant))
            write(EventFAQ, FAQS, lambda i, row: EventFAQ(
                event=event, question_en=row[0], answer_en=row[1], sort_order=i, tenant=tenant))

            # The itinerary rows are shown as the timeline inside "Event Schedule".
            if refresh or not event.itineraries.exists():
                event.itineraries.all().delete()
                day = EventItinerary.objects.create(event=event, day_number=1, title_en='Match day',
                                                    title_te='మ్యాచ్ డే', title_hi='मैच डे')
                EventItineraryItem.objects.bulk_create([
                    EventItineraryItem(itinerary=day, time_label=label, text_en=title, detail_en=detail,
                                       sort_order=i, tenant=tenant)
                    for i, (label, title, detail) in enumerate(TIMELINE)])

            event.refresh_from_db()
            event.publish()  # also moves the approved translations to PUBLISHED

        self.stdout.write(self.style.SUCCESS(
            f"{'Created' if created else 'Updated'} and published event '{SLUG}' (popup on"
            f"{', page content refreshed' if refresh else ''}"
            f"{'' if poster else '; no poster uploaded, so the website uses its bundled poster'})."))
