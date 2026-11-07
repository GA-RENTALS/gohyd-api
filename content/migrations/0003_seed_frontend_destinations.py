from django.db import migrations
from django.utils.text import slugify


DESTINATIONS = [
    ("Charminar", "Old City", "17.3616", "78.4747", "The 1591 landmark at the heart of the Old City."),
    ("Laad Bazaar", "Old City", "17.3609", "78.4722", "Bangles, pearls and bridal shopping beside the Charminar."),
    ("Chowmahalla Palace", "Old City", "17.3578", "78.4719", "The Nizams' palace complex with its courtyards and lawns."),
    ("Golconda Fort", "West of the city", "17.3833", "78.4011", "Granite ramparts of the Qutb Shahi citadel."),
    ("Qutb Shahi Tombs", "Ibrahim Bagh", "17.3947", "78.3944", "Domed royal tombs, beautifully lit after dark."),
    ("Hussain Sagar", "Tank Bund", "17.4239", "78.4738", "The lake, the Buddha statue and the Tank Bund promenade."),
    ("Durgam Cheruvu Cable Bridge", "Madhapur", "17.4321", "78.3869", "A cable-stayed bridge, lit up after dark."),
    ("HITEC City", "The west", "17.4435", "78.3772", "The tech corridor's glass towers at night."),
    ("Shilparamam", "Madhapur", "17.4524", "78.3817", "Arts and crafts village with stalls and live artists."),
    ("Ananthagiri Hills", "Vikarabad district", "17.32", "77.87", "Forested hills for trails and day trips. Pin is approximate; about 80 km west of the city."),
    ("Khajaguda", "Hyderabad", "17.409", "78.348", "Trekking escape in Hyderabad. Pin is approximate."),
    ("Rachakonda", "Telangana", "17.242", "78.796", "Forts escape in Telangana. Pin is approximate."),
    ("Pocharam", "Telangana", "18.015", "78.256", "Rides escape in Telangana. Pin is approximate."),
    ("Narsapur Forest Trek", "Medak", "17.728", "78.283", "Trekking escape in Medak. Pin is approximate."),
    ("Medak Bike Ride", "Medak", "18.045", "78.264", "Rides escape in Medak. Pin is approximate."),
    ("Somasila", "Telangana", "16.283", "78.978", "Day Trips escape in Telangana. Pin is approximate."),
    ("Vizag Colony", "Telangana", "16.7", "79.2", "Day Trips escape in Telangana. Pin is approximate."),
    ("Koil Sagar", "Telangana", "16.689", "77.696", "Lakes escape in Telangana. Pin is approximate."),
    ("Srirangapuram and Pangal Fort", "Telangana", "16.333", "78.055", "Forts escape in Telangana. Pin is approximate."),
    ("Killa Ganpur", "Telangana", "16.42", "78.03", "Forts escape in Telangana. Pin is approximate."),
    ("Adilabad", "Telangana", "19.6641", "78.532", "Day Trips escape in Telangana. Pin is approximate."),
    ("Tadoba-Andhari Tiger Reserve", "Maharashtra", "20.2", "79.34", "Wildlife escape in Maharashtra. Pin is approximate."),
    ("Pench Day Safari", "Madhya Pradesh", "21.7", "79.27", "Wildlife escape in Madhya Pradesh. Pin is approximate."),
    ("Chincholi", "Karnataka", "17.466", "77.419", "Day Trips escape in Karnataka. Pin is approximate."),
    ("Srirangapuram and Pamapuram", "Telangana", "16.34", "78.06", "Day Trips escape in Telangana. Pin is approximate."),
    ("Laknavaram Lake", "Telangana", "18.07", "79.963", "Lakes escape in Telangana. Pin is approximate."),
    ("Mallela Theertham", "Telangana", "16.259", "78.766", "Waterfalls escape in Telangana. Pin is approximate."),
    ("Koilsagar Dam Trek and Rappelling", "Telangana", "16.695", "77.7", "Adventure escape in Telangana. Pin is approximate."),
    ("Nagarjuna Sagar", "Telangana", "16.575", "79.314", "Lakes escape in Telangana. Pin is approximate."),
    ("Umamaheshwaram", "Telangana", "16.409", "78.727", "Temples escape in Telangana. Pin is approximate."),
    ("Pandavula Gutta", "Khammam", "17.247", "80.15", "Trekking escape in Khammam. Pin is approximate."),
    ("Bidar Fort", "Karnataka", "17.914", "77.526", "Forts escape in Karnataka. Pin is approximate."),
    ("Vemulawada", "Telangana", "18.464", "78.875", "Temples escape in Telangana. Pin is approximate."),
    ("Kuntala Falls", "Adilabad", "19.119", "78.368", "Waterfalls escape in Adilabad. Pin is approximate."),
    ("Edupayala Vana Durga Bhavani Temple", "Medak", "18.056", "78.297", "Temples escape in Medak. Pin is approximate."),
    ("Jurala Dam", "Telangana", "16.29", "77.81", "Lakes escape in Telangana. Pin is approximate."),
    ("Koilkonda Fort and Koilsagar Dam", "Telangana", "16.705", "77.76", "Forts escape in Telangana. Pin is approximate."),
    ("Ethipothala Falls", "Andhra Pradesh", "16.6", "79.285", "Waterfalls escape in Andhra Pradesh. Pin is approximate."),
    ("Kinnerasani Dam and Wildlife Sanctuary", "Telangana", "17.62", "80.7", "Wildlife escape in Telangana. Pin is approximate."),
    ("Bheemuni Paadam Waterfalls", "Near Warangal", "17.9", "79.7", "Waterfalls escape near Warangal. Pin is approximate."),
    ("Damagundam Ramalingeshwara Temple", "Telangana", "17.35", "77.76", "Temples escape in Telangana. Pin is approximate."),
    ("Kotpally Reservoir", "Telangana", "17.39", "77.86", "Lakes escape in Telangana. Pin is approximate."),
    ("Vizag Colony Backwaters", "Telangana", "16.71", "79.21", "Lakes escape in Telangana. Pin is approximate."),
    ("Bogata Waterfall", "Telangana", "18.005", "80.465", "Waterfalls escape in Telangana. Pin is approximate."),
    ("Kavadipally Forest Trek", "Telangana", "17.67", "78.41", "Trekking escape in Telangana. Pin is approximate."),
    ("Kondapochamma Lake", "Telangana", "17.864", "78.653", "Lakes escape in Telangana. Pin is approximate."),
    ("Dharmapuri", "Telangana", "18.91", "79.41", "Temples escape in Telangana. Pin is approximate."),
    ("Muthyamdhara Waterfalls", "Telangana", "18.38", "80.25", "Waterfalls escape in Telangana. Pin is approximate."),
    ("Moula Ali Hill", "Hyderabad", "17.462", "78.553", "Trekking escape in Hyderabad. Pin is approximate."),
    ("Chityal Hills", "Telangana", "17.2", "78.95", "Trekking escape in Telangana. Pin is approximate."),
    ("Gunrock Hill", "Hyderabad", "17.459", "78.508", "Trekking escape in Hyderabad. Pin is approximate."),
    ("Kondamadugu Hills", "Telangana", "17.33", "78.88", "Trekking escape in Telangana. Pin is approximate."),
    ("Octopus View Point", "Telangana", "17.338", "77.85", "Viewpoints escape in Telangana. Pin is approximate."),
]


def seed_frontend_destinations(apps, schema_editor):
    Destination = apps.get_model("content", "Destination")
    DestinationTranslation = apps.get_model("content", "DestinationTranslation")

    for sort_order, (name, region, latitude, longitude, summary) in enumerate(DESTINATIONS):
        slug = slugify(name)
        destination, _ = Destination.objects.using(schema_editor.connection.alias).get_or_create(
            slug=slug,
            defaults={
                "status": "DRAFT",
                "region": region,
                "latitude": latitude,
                "longitude": longitude,
                "is_hyderabad_explore": True,
                "sort_order": sort_order,
            },
        )
        DestinationTranslation.objects.using(schema_editor.connection.alias).get_or_create(
            destination=destination,
            language="en",
            defaults={"title": name, "summary": summary, "status": "DRAFT"},
        )


class Migration(migrations.Migration):
    dependencies = [("content", "0002_initial")]

    operations = [
        migrations.RunPython(seed_frontend_destinations, migrations.RunPython.noop),
    ]
