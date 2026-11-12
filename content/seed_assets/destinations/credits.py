"""Who took each destination photo and under which licence (all from Wikimedia Commons).

Creative Commons BY / BY-SA licences require crediting the author, so each uploaded photo keeps this line in MediaAsset.credit.
File names say where a photo goes: "golconda-fort.jpg" is the cover, "golconda-fort--2.jpg" the 2nd gallery photo.
"""
WIKI = 'https://commons.wikimedia.org/wiki/File%3A'

PHOTOS = {
    'ananthagiri-hills.jpg': ('Praveen120', 'CC BY-SA 3.0', 'Ananthagiri_Hills.JPG', 'Forested hills of Ananthagiri'),
    'ananthagiri-hills--2.jpg': ('Tanukusreeharsha', 'CC BY-SA 4.0', 'Ananthagiri_Hills_Trekking_Area.jpg', 'A shaded forest trail in Ananthagiri Hills'),
    'durgam-cheruvu-cable-bridge.jpg': ('iMahesh', 'CC BY-SA 4.0', 'Long_Exposure_of_Cable_bridge_on_Durgam_Cheruvu.jpg', 'The Durgam Cheruvu cable bridge lit up at night'),
    'durgam-cheruvu-cable-bridge--2.jpg': ('iMahesh', 'CC BY-SA 4.0', 'Aerial_view_of_Durgam_cheruvu_and_Hitech_CIty.jpg', 'Aerial view of Durgam Cheruvu lake and HITEC City'),
    'charminar.jpg': ('Jagannathsrs', 'CC BY-SA 4.0', 'Charminar_night_1.jpg', 'Charminar at night with the bazaar around it'),
    'charminar--2.jpg': ('Anumeha Shukla', 'CC BY-SA 3.0', 'Charminar_at_Sunset.JPG', 'Charminar at sunset'),
    'charminar--3.jpg': ('iMahesh', 'CC BY-SA 4.0', 'Perspective_view_of_Charminar_at_night_%28June_2019%29.jpg', 'Charminar seen from below at night'),
    'chowmahalla-palace.jpg': ('Kavali Chandrakanth KCK', 'CC0', 'Chowmahalla_Palace_Hyderabad_Tealagana_India.jpg', 'Chowmahalla Palace facade and clock tower'),
    'golconda-fort.jpg': ('Bernard Gagnon', 'CC BY-SA 3.0', 'Golconda_Fort_005.jpg', 'Stone walls of Golconda Fort'),
    'golconda-fort--2.jpg': ('iMahesh', 'CC BY-SA 4.0', 'Golconda_Fort_and_Hyderabad_city.jpg', 'Golconda Fort with the Hyderabad skyline behind'),
    'hitec-city.jpg': ('Mohammad Anees Qamar', 'CC BY 4.0', 'Hyderabad_Hi-Tech_City_Skyline_at_Night_%E2%80%93_India%27s_Emerging_Silicon_Valley_%282025%29.jpg', 'HITEC City skyline at night'),
    'hussain-sagar.jpg': ('iMahesh', 'CC BY-SA 4.0', 'Long_Exposure_at_Tank_bunk_Buddha_statue.jpg', 'The Buddha statue on Hussain Sagar from Tank Bund'),
    'hussain-sagar--2.jpg': ('Nikhilb239', 'CC BY-SA 4.0', 'Buddha_Statue%2C_Hussain_Sagar%2C_Hyd.JPG', 'The Buddha statue on Hussain Sagar at night'),
    'laad-bazaar.jpg': ('deadrat', 'CC BY 4.0', 'Laad_Bazaar_as_seen_from_charminar.jpg', 'Laad Bazaar seen from the Charminar'),
    'laad-bazaar--2.jpg': ('Abhinaba Basu', 'CC BY 2.0', 'Laad_Bazaar_Bangles.jpg', 'Colourful lac bangles at Laad Bazaar'),
    'qutb-shahi-tombs.jpg': ('iMahesh', 'CC BY-SA 4.0', 'Qutub_Shahi_Tombs_illuminated.jpg', 'The Qutb Shahi Tombs lit up at night'),
    'shilparamam.jpg': ('Nayan j Nath', 'CC BY-SA 4.0', 'A_vendor_at_Shilparamam_Telengana.jpg', 'A craft vendor at Shilparamam'),
    'shilparamam--2.jpg': ('Nayan j Nath', 'CC BY-SA 4.0', 'An_artist_drawing_a_portrait_of_a_client_at_Shilparamam_village.jpg', 'An artist drawing a portrait at Shilparamam'),
}


def credit_line(filename):
    author, licence, page, _ = PHOTOS[filename]
    return f'{author} · {licence} · Wikimedia Commons ({WIKI}{page})'[:255]


def alt_text(filename):
    return PHOTOS[filename][3]
