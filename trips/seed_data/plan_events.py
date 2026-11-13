"""Page copy for the 50 GoHyderabad plan cards (components/site/data/plans.ts in gohyd-ui), seeded as Events.

Written from public sources (Telangana Tourism, district websites, travel guides). Distances are approximate road
distances from Hyderabad. No dates: every event shows as "Upcoming" until staff add a date in the admin panel.
`title` must match the plan card title exactly — the card links to /events/<slug of title>.

Each entry: title, cat, region, km, duration, difficulty, best, venue, summary, body (paragraphs), highlights,
stops (itinerary: (title, detail)). Optional: faqs [(q, a)], extra_bring [..].
"""

PLAN_EVENTS = [
    # ---------------- Trekking ----------------
    dict(title='Khajaguda', cat='trekking', region='Hyderabad', km='In the city (Gachibowli / Nanakramguda)',
         duration='Half day (early morning)', difficulty='Easy to moderate', best='October to February',
         venue='Khajaguda Hills, near Khajaguda Lake, Hyderabad',
         summary='A sunrise scramble over the giant granite boulders of Khajaguda, right next to the Financial District.',
         body=['Khajaguda is one of the last big patches of the Deccan’s ancient granite rock formations inside '
               'Hyderabad city. The hill sits between Gachibowli, Nanakramguda and Manikonda, with Khajaguda Lake at '
               'its foot and the Financial District skyline on the horizon.',
               'We start before sunrise, climb and boulder our way up the rocky ridges, and watch the sun come up over '
               'the city. It is a short, beginner-friendly outing that still feels like a proper trek, and a great way '
               'to meet the GoHyderabad community.'],
         highlights=['Sunrise over the Hyderabad skyline', 'Natural Deccan granite rock formations',
                     'Beginner-friendly bouldering sections', 'Back in the city before breakfast'],
         stops=[('Meet at the base', 'Gather near Khajaguda Lake, introductions and safety briefing.'),
                ('Climb to the ridge', 'Trail walk and light bouldering over the granite rocks.'),
                ('Sunrise at the top', 'Photos, rest and views of the Financial District.'),
                ('Descend', 'Walk back down to the base.')]),

    dict(title='Narsapur Forest Trek', cat='trekking', region='Medak', km='Approx. 50 km',
         duration='Full day', difficulty='Easy to moderate', best='July to February',
         venue='Narsapur Reserve Forest, Medak district',
         summary='A forest walk through the green Narsapur reserve forest and its lake, an hour from the city.',
         body=['Narsapur Reserve Forest, on the Hyderabad–Medak road, is one of the closest real forests to the '
               'city. Dense dry-deciduous woods, a quiet lake, an urban forest park and plenty of birdlife make it a '
               'favourite escape, especially after the monsoon when everything turns green.',
               'This trek follows forest trails at an easy pace with time to stop for birds, the lake and photographs. '
               'It suits first-time trekkers and families as well as regular hikers.'],
         highlights=['Dense reserve forest close to Hyderabad', 'Narsapur lake and urban forest park',
                     'Good birdwatching in the early hours', 'Easy pace, suitable for beginners'],
         stops=[('Arrive at Narsapur forest', 'Briefing at the forest entry.'),
                ('Forest trail walk', 'Guided walk along the forest tracks.'),
                ('Lakeside break', 'Rest and snacks near Narsapur lake.'),
                ('Urban forest park', 'Short walk through the park and watchtower area, if open.')]),

    dict(title='Pandavula Gutta – Khammam', cat='trekking', region='Jayashankar Bhupalpally (Warangal region)',
         km='Approx. 200 km', duration='Full day', difficulty='Moderate', best='October to February',
         venue='Pandavula Gutta, Regonda mandal, Jayashankar Bhupalpally district',
         summary='Trek to a prehistoric rock-art site with cave paintings thousands of years older than the Kakatiyas.',
         body=['Pandavula Gutta is a cluster of sandstone hills with natural caves and rock shelters, famous for '
               'prehistoric rock paintings — animals, hunting scenes and symbols painted in red and white ochre. It '
               'is one of the most important rock-art sites in Telangana, and local legend links the caves to the '
               'Pandavas of the Mahabharata.',
               'The trek winds through rock formations, narrow passages and shelters, with plenty of time to look at '
               'the paintings and enjoy the views over the surrounding forest. The rock faces here are also used for '
               'climbing and rappelling.'],
         highlights=['Prehistoric rock paintings in natural shelters', 'Sandstone caves and rock formations',
                     'Views over the forested countryside', 'History, legend and adventure in one day'],
         stops=[('Arrive at Pandavula Gutta', 'Briefing and start of the trail.'),
                ('Rock shelters and paintings', 'Explore the caves and prehistoric rock art.'),
                ('Hilltop viewpoint', 'Climb to the top for views over the area.'),
                ('Descend and lunch', 'Walk back and lunch nearby.')]),

    dict(title='Kavadipally Forest Trek', cat='trekking', region='Rangareddy', km='Approx. 35 km',
         duration='Half day', difficulty='Easy', best='July to February',
         venue='Kavadipally Reserve Forest, near Hayathnagar',
         summary='A quick forest escape on the eastern edge of the city, with rocky trails and a lake view.',
         body=['Kavadipally sits on the eastern outskirts of Hyderabad, beyond Hayathnagar, where the city gives way '
               'to scrub forest, rocky hillocks and a village lake. It is quiet, green after the rains and close '
               'enough for a morning outing.',
               'This short trek follows forest and rock trails with a lake view at the end — ideal for first-timers '
               'and anyone wanting a nature walk without a long drive.'],
         highlights=['Close to the city — easy morning outing', 'Rocky hillocks and scrub forest',
                     'Kavadipally lake views', 'Beginner-friendly trail'],
         stops=[('Meet and drive to Kavadipally', 'Group meet-up and short drive out of the city.'),
                ('Forest trail', 'Walk through the forest and over the rocks.'),
                ('Lake viewpoint', 'Rest, snacks and photos.'),
                ('Return', 'Walk back to the start point.')]),

    dict(title='Moula Ali Hill', cat='trekking', region='Hyderabad', km='Approx. 12 km (Secunderabad)',
         duration='2–3 hours', difficulty='Easy', best='All year (early morning or evening)',
         venue='Moula Ali Hill, Moula Ali, Secunderabad',
         summary='Climb the rock-cut steps of Moula Ali hill to a historic dargah and a 360° view of the twin cities.',
         body=['Moula Ali is a large granite hill in north-east Secunderabad, crowned by the Moula Ali Dargah, which '
               'dates back to the Qutb Shahi period. Around 500 rock-cut steps lead to the top, passing old '
               'gateways and arches along the way.',
               'From the summit you get one of the best panoramas of Hyderabad and Secunderabad, especially at sunrise '
               'and sunset. A short, easy climb with plenty of history.'],
         highlights=['Around 500 rock-cut steps to the top', 'Historic Qutb Shahi-era dargah',
                     '360° view of the twin cities', 'Great sunrise and sunset spot'],
         stops=[('Meet at the foot of the hill', 'Introductions and a short history of the hill.'),
                ('Climb the steps', 'Steady climb through the old gateways.'),
                ('Summit', 'Views, photos and time at the top.'),
                ('Descend', 'Walk down together.')],
         faqs=[('Is there a dress code?', 'The hilltop has a place of worship, so please dress modestly and respect the site.')]),

    dict(title='Chityal Hills', cat='trekking', region='Telangana', km='Approx. 90 km',
         duration='Full day', difficulty='Moderate', best='October to March',
         venue='Chityal Hills, Telangana',
         summary='Three green hill ranges, forest trails and a valley known for camping — a lesser-known weekend trek.',
         body=['Chityal Hills is an offbeat trekking spot roughly 90 km from Hyderabad. The area has three small hill '
               'ranges covered in scrub forest and greenery, with birdlife, quiet trails and a valley that trekkers '
               'also use for camping.',
               'This day trek takes in one of the ranges at a relaxed pace, with time for views and photographs. It is '
               'a good next step for people who have done the city hills and want something longer.'],
         highlights=['Three hill ranges to explore', 'Green forest trails and birdlife',
                     'Quiet, offbeat and uncrowded', 'Valley views from the ridge'],
         stops=[('Arrive at Chityal', 'Briefing and start of the trek.'),
                ('Ridge trail', 'Climb along the hill range.'),
                ('Top and valley views', 'Rest, snacks and photos.'),
                ('Descend', 'Walk back to the base.')]),

    dict(title='Gunrock Hill', cat='trekking', region='Hyderabad', km='Approx. 15 km (Secunderabad)',
         duration='2–3 hours', difficulty='Easy', best='November to March',
         venue='Gun Rock, Trimulgherry, Secunderabad Cantonment',
         summary='A short heritage climb to Gun Rock and its 1798 water tank, with views of Moula Ali and the cantonment.',
         body=['Gun Rock is a granite outcrop in the Secunderabad Cantonment near Trimulgherry. It was part of the '
               'British-era Trimulgherry Entrenchment and takes its name from the guns once placed here to guard the '
               'cantonment. At the top is a historic water tank built in 1798 during Nizam Sikander Jah’s time to '
               'supply the military area.',
               'It is a beginner-friendly boulder climb with plenty of history, and from the top you can see Moula Ali '
               'and Anand Buddha Vihar.'],
         highlights=['Historic 1798 water tank at the top', 'Part of the old Trimulgherry Entrenchment',
                     'Boulders that suit beginners', 'Views of Moula Ali and the cantonment'],
         stops=[('Meet near Trimulgherry', 'Introductions and heritage briefing.'),
                ('Climb Gun Rock', 'Easy boulder climb from the north side.'),
                ('Water tank and summit', 'History stories, views and photos.'),
                ('Descend', 'Walk back down.')],
         faqs=[('Is the hill open to the public?', 'Gun Rock is inside the Cantonment area. Access rules can change, '
                'so the team will confirm the route and entry before the outing.')]),

    dict(title='Kondamadugu Hills', cat='trekking', region='Yadadri Bhuvanagiri', km='Approx. 50 km',
         duration='Half day', difficulty='Moderate', best='October to February',
         venue='Kondamadugu, near Bibinagar, Yadadri Bhuvanagiri district',
         summary='Granite hills near Bibinagar known for bouldering, rock climbing and wide sunrise views.',
         body=['The rocky hills around Kondamadugu, near Bibinagar on the Warangal highway, are one of Hyderabad’s '
               'favourite spots for bouldering and rock-climbing practice. Huge granite boulders sit on the ridges '
               'above farmland and small lakes.',
               'This outing combines a short trek with easy scrambling on the rocks, finishing with views across the '
               'countryside.'],
         highlights=['Popular bouldering and climbing rocks', 'Short drive on the Warangal highway',
                     'Sunrise views over farmland and lakes', 'Mix of trekking and scrambling'],
         stops=[('Arrive at Kondamadugu', 'Briefing and warm-up.'),
                ('Trek to the ridge', 'Trail and scramble up the granite hill.'),
                ('Boulder area', 'Try easy bouldering with guidance.'),
                ('Descend', 'Walk back and wrap up.')]),

    # ---------------- Forts ----------------
    dict(title='Rachakonda', cat='forts', region='Rangareddy / Yadadri', km='Approx. 65 km',
         duration='Full day', difficulty='Moderate', best='October to February',
         venue='Rachakonda Fort, Rachakonda hills',
         summary='Explore the hilltop ruins of the 14th-century Recherla Velama fort, hidden in the Rachakonda hills.',
         body=['Rachakonda was the capital of the Recherla Velama kings in the 14th and 15th centuries. Today the '
               'fort lies in ruins across the Rachakonda hills — massive granite gateways, fortification walls, '
               'temples and step-wells built from huge stone blocks without mortar.',
               'We hike up through the old fort walls, explore the ruins and temples, and take in sweeping views of '
               'the forested hills. Few people visit, which makes it feel like a real discovery.'],
         highlights=['14th-century Recherla Velama capital', 'Massive mortarless stone gateways and walls',
                     'Hilltop temples and step-wells', 'Quiet, offbeat heritage trek'],
         stops=[('Arrive at Rachakonda', 'Briefing and a short history of the fort.'),
                ('Trek up the fort hill', 'Climb past the gateways and fortification walls.'),
                ('Explore the ruins', 'Temples, step-wells and viewpoints.'),
                ('Descend and lunch', 'Walk back and lunch nearby.')]),

    dict(title='Srirangapuram & Pangal Fort', cat='forts', region='Wanaparthy', km='Approx. 170 km',
         duration='Full day', difficulty='Easy to moderate', best='October to February',
         venue='Srirangapuram and Pangal, Wanaparthy district',
         summary='An 18th-century lakeside temple at Srirangapuram and a climb to the hilltop Pangal Fort.',
         body=['Srirangapuram is home to the Sri Ranganayaka Swamy Temple, built by the Rajas of the Wanaparthy '
               'Samsthanam in the 18th century on the bund of the Ranga Samudram lake. Its carvings, gopuram and '
               'lakeside setting make it one of the most photogenic temples in Telangana.',
               'Pangal Fort sits on a hill near Wanaparthy and is reached by a short trek. The ruins, walls and '
               'bastions look over the plains and lakes of the region.'],
         highlights=['Sri Ranganayaka Swamy Temple on the lake bund', 'Carvings and a classic South Indian gopuram',
                     'Short trek to the hilltop Pangal Fort', 'Lake and countryside views'],
         stops=[('Srirangapuram temple', 'Visit the Ranganayaka Swamy Temple and the lake.'),
                ('Lunch', 'Local lunch in the area.'),
                ('Pangal Fort trek', 'Climb to the fort and explore the ruins.'),
                ('Sunset view', 'Views from the fort before heading back.')]),

    dict(title='Killa Ganpur', cat='forts', region='Mahabubnagar region', km='Approx. 120 km',
         duration='Full day', difficulty='Moderate', best='October to February',
         venue='Ghanpur (Killa Ganpur) Fort, Mahabubnagar region',
         summary='A climb to the hill fort of Ganpur, with stone walls, gateways and wide views of the Deccan plateau.',
         body=['Killa Ganpur is a hill fort on a rocky granite hill, with layers of stone walls, gateways, bastions '
               'and water tanks. Like many Deccan forts it changed hands between local rulers over the centuries.',
               'The trek follows the old path through the fortifications to the top, where you get views over the '
               'plains, lakes and villages below. A good heritage-and-hike day out.'],
         highlights=['Hill fort with stone walls and bastions', 'Old gateways and water tanks',
                     'Views over the Deccan plateau', 'Few tourists'],
         stops=[('Arrive at Ganpur', 'Briefing at the base of the fort hill.'),
                ('Climb through the fortifications', 'Follow the old path through the gateways.'),
                ('Fort top', 'Explore the ruins and viewpoints.'),
                ('Descend and lunch', 'Walk back and lunch nearby.')]),

    dict(title='Bidar Fort', cat='forts', region='Bidar, Karnataka', km='Approx. 140 km',
         duration='Full day', difficulty='Easy', best='October to March',
         venue='Bidar Fort, Bidar, Karnataka',
         summary='The 15th-century Bahmani capital: Bidar Fort, Rangin Mahal, Mahmud Gawan Madrasa and the Bahmani tombs.',
         body=['Bidar became the capital of the Bahmani Sultanate in the 15th century, and its fort is one of the '
               'largest in the Deccan, with kilometres of walls, moats and gateways. Inside you can see the Rangin '
               'Mahal with its tile work and wood carving, the Solah Khamba mosque and the royal gardens.',
               'The day also covers the Mahmud Gawan Madrasa in the old town and the domed Bahmani tombs at '
               'Ashtur — a full day of Indo-Islamic architecture just across the Karnataka border.'],
         highlights=['One of the largest forts in the Deccan', 'Rangin Mahal tile work and carvings',
                     'Mahmud Gawan Madrasa', 'Bahmani tombs at Ashtur'],
         stops=[('Bidar Fort', 'Walk the walls, gateways, Rangin Mahal and Solah Khamba mosque.'),
                ('Lunch', 'Lunch in Bidar town.'),
                ('Mahmud Gawan Madrasa', 'The 15th-century madrasa in the old town.'),
                ('Bahmani tombs, Ashtur', 'The domed royal tombs before heading back.')]),

    dict(title='Koilkonda Fort & Koilsagar Dam', cat='forts', region='Mahabubnagar', km='Approx. 120 km',
         duration='Full day', difficulty='Moderate', best='October to February',
         venue='Koilkonda and Koilsagar, Mahabubnagar district',
         summary='A hill-fort trek at Koilkonda followed by the reservoir and hills of Koilsagar Dam.',
         body=['Koilkonda Fort stands on a high granite hill in Mahabubnagar district, with gateways, walls, '
               'mosques and water tanks from the Qutb Shahi era. The climb is steep in parts but short, and the views '
               'from the top stretch across the plateau.',
               'In the afternoon we head to Koilsagar Dam, a reservoir on the Peddavagu stream ringed by hills — a '
               'lovely place to relax by the water as the sun goes down.'],
         highlights=['Qutb Shahi-era hill fort', 'Gateways, walls and stone tanks',
                     'Koilsagar reservoir among the hills', 'Fort trek plus sunset by the water'],
         stops=[('Koilkonda Fort trek', 'Climb to the fort and explore the ruins.'),
                ('Lunch', 'Lunch in the area.'),
                ('Koilsagar Dam', 'Reservoir and viewpoints.'),
                ('Sunset', 'Relax by the water before heading back.')]),

    # ---------------- Day trips ----------------
    dict(title='Ananthagiri Hills – Day', cat='day-trips', region='Vikarabad', km='Approx. 80 km',
         duration='Full day', difficulty='Easy', best='July to February',
         venue='Ananthagiri Hills, Vikarabad',
         summary='Forests, viewpoints and the Anantha Padmanabha Swamy temple in the hills where the Musi river begins.',
         body=['Ananthagiri Hills near Vikarabad is one of the most popular getaways from Hyderabad. The Musi river '
               'originates here, and the dense forest, misty mornings and coffee-coloured hills make it especially '
               'beautiful after the monsoon.',
               'The day covers forest trails, viewpoints and the ancient Anantha Padmanabha Swamy temple, with an '
               'optional stop at Kotpally reservoir nearby.'],
         highlights=['Forest trails where the Musi river begins', 'Anantha Padmanabha Swamy temple',
                     'Valley viewpoints', 'Misty and green after the monsoon'],
         stops=[('Ananthagiri viewpoint', 'Arrive and take in the valley views.'),
                ('Forest trail walk', 'Easy trek through the forest.'),
                ('Anantha Padmanabha Swamy temple', 'Visit the hilltop temple.'),
                ('Kotpally reservoir (optional)', 'Lakeside stop before heading back.')]),

    dict(title='Somasila – Day', cat='day-trips', region='Nagarkurnool', km='Approx. 180 km',
         duration='Full day', difficulty='Easy', best='August to February',
         venue='Somasila, Kollapur, Nagarkurnool district',
         summary='Krishna river backwaters, the Someshwara temple complex and island views at Somasila.',
         body=['Somasila sits on the Krishna river backwaters of the Srisailam reservoir near Kollapur. The village is '
               'known for its group of ancient Shiva temples, including the Someshwara temple, some of which were '
               'relocated here when the dam was built.',
               'The day includes the temples, the riverside ghats and backwater viewpoints, and — when operating — a '
               'boat ride on the Krishna.'],
         highlights=['Krishna river backwaters', 'Ancient Someshwara temple complex',
                     'Island and hill views', 'Boat rides when operating'],
         stops=[('Somasila temples', 'Visit the Someshwara temple complex.'),
                ('Riverside ghats', 'Time on the Krishna backwaters.'),
                ('Lunch', 'Lunch in the area.'),
                ('Backwater viewpoint', 'Views and photos before heading back.')]),

    dict(title='Vizag Colony – Day', cat='day-trips', region='Nalgonda', km='Approx. 160 km',
         duration='Full day', difficulty='Easy', best='August to February',
         venue='Vizag Colony, Nagarjuna Sagar backwaters, Nalgonda district',
         summary='A beach-like day on the Nagarjuna Sagar backwaters — sand, water and big open skies.',
         body=['Vizag Colony is a fishing settlement on the Nagarjuna Sagar backwaters in Nalgonda district. With its '
               'wide sandy shore and calm water stretching to the horizon, it is often called Hyderabad’s nearest '
               '“beach”.',
               'Spend the day by the water, take a boat ride with the local fishermen when available, and stay for '
               'the sunset over the reservoir.'],
         highlights=['Sandy shore on the Nagarjuna Sagar backwaters', 'Boat rides with local fishermen',
                     'Wide-open water views', 'Spectacular sunsets'],
         stops=[('Arrive at Vizag Colony', 'Settle in by the water.'),
                ('Boat ride', 'Ride on the backwaters, when available.'),
                ('Lunch', 'Fresh local lunch.'),
                ('Sunset', 'Sunset over the reservoir before heading back.')]),

    dict(title='Adilabad', cat='day-trips', region='Adilabad', km='Approx. 300 km',
         duration='Full day (long drive)', difficulty='Easy to moderate', best='August to January',
         venue='Adilabad district',
         summary='Waterfalls, forests and tribal villages of Adilabad — Kuntala, Pochera and the Kawal forests.',
         body=['Adilabad, in the far north of Telangana, is a land of waterfalls, teak forests and Gond tribal '
               'culture. Kuntala Falls on the Kadam river is the highest waterfall in the state, and Pochera Falls '
               'nearby tumbles over rocky steps.',
               'This trip covers the main falls and the forested countryside, best seen after the monsoon when the '
               'water is at its fullest.'],
         highlights=['Kuntala Falls — the highest in Telangana', 'Pochera Falls',
                     'Teak forests near Kawal', 'Gond tribal culture'],
         stops=[('Kuntala Falls', 'Walk down to the falls.'),
                ('Lunch', 'Lunch in the area.'),
                ('Pochera Falls', 'Visit the rock-step falls.'),
                ('Head back', 'Long drive back to Hyderabad.')]),

    dict(title='Chincholi', cat='day-trips', region='Kalaburagi, Karnataka', km='Approx. 150 km',
         duration='Full day', difficulty='Easy', best='July to February',
         venue='Chincholi Wildlife Sanctuary, Kalaburagi district, Karnataka',
         summary='Karnataka’s first dry-land wildlife sanctuary, with forests, Chandrampalli dam and small waterfalls.',
         body=['Chincholi Wildlife Sanctuary, just across the Karnataka border, protects dry-deciduous forest with '
               'teak, sandalwood and bamboo. Deer, peafowl and many birds live here, and the Chandrampalli dam and '
               'small seasonal waterfalls add to the scenery.',
               'The day includes forest drives or walks, the dam and viewpoints — a green, quiet day out close to '
               'the Telangana border.'],
         highlights=['Dry-land wildlife sanctuary', 'Chandrampalli dam',
                     'Seasonal waterfalls after the monsoon', 'Birds, deer and peafowl'],
         stops=[('Chincholi sanctuary', 'Forest drive or walk.'),
                ('Chandrampalli dam', 'Reservoir and viewpoints.'),
                ('Lunch', 'Lunch in the area.'),
                ('Waterfall / viewpoint', 'Seasonal falls before heading back.')]),

    dict(title='Srirangapuram + Pamapuram', cat='day-trips', region='Wanaparthy', km='Approx. 170 km',
         duration='Full day', difficulty='Easy', best='October to February',
         venue='Srirangapuram, Pebbair mandal, Wanaparthy district',
         summary='The lakeside Sri Ranganayaka Swamy Temple of Srirangapuram plus the villages and countryside nearby.',
         body=['Srirangapuram’s Sri Ranganayaka Swamy Temple was built by the Rajas of the Wanaparthy Samsthanam in '
               'the 18th century and sits on the bund of the Ratna Pushkarini / Ranga Samudram lake. Its gopuram, '
               'carvings and reflections in the water make it a favourite of photographers.',
               'The day pairs the temple with Pamapuram and the surrounding Wanaparthy countryside — lakes, villages '
               'and heritage stops.'],
         highlights=['18th-century Ranganayaka Swamy Temple', 'Temple reflections on the lake',
                     'Wanaparthy heritage and countryside', 'Relaxed, easy day'],
         stops=[('Srirangapuram temple', 'Temple visit and time by the lake.'),
                ('Lunch', 'Local lunch.'),
                ('Pamapuram', 'Visit Pamapuram and the countryside nearby.'),
                ('Head back', 'Return to Hyderabad.')]),

    # ---------------- Camping ----------------
    dict(title='Ananthagiri Hills – Camping', cat='camping', region='Vikarabad', km='Approx. 80 km',
         duration='Overnight (2 days, 1 night)', difficulty='Easy', best='October to February',
         venue='Ananthagiri Hills, Vikarabad',
         summary='A night under the stars in the Ananthagiri forest, with a campfire and a misty sunrise trek.',
         body=['Ananthagiri Hills is Hyderabad’s classic camping getaway — cool nights, forest all around and mist '
               'rolling over the valleys in the morning.',
               'We arrive in the afternoon, set up camp, enjoy a campfire evening with games and music, sleep in tents '
               'and wake up for a sunrise trek through the forest.'],
         highlights=['Overnight tent stay in the hills', 'Campfire, music and games',
                     'Stargazing away from the city lights', 'Sunrise forest trek'],
         stops=[('Day 1 · Arrive and set up camp', 'Check in at the campsite and settle in.'),
                ('Day 1 · Evening', 'Campfire, games, dinner and stargazing.'),
                ('Day 2 · Sunrise trek', 'Early forest trek to a viewpoint.'),
                ('Day 2 · Breakfast and pack up', 'Breakfast, pack up and head back.')]),

    dict(title='Somasila Camping', cat='camping', region='Nagarkurnool', km='Approx. 180 km',
         duration='Overnight (2 days, 1 night)', difficulty='Easy', best='October to February',
         venue='Somasila, Krishna backwaters, Nagarkurnool district',
         summary='Camp beside the Krishna backwaters at Somasila, with temples, boating and a riverside campfire.',
         body=['Somasila, on the Srisailam backwaters of the Krishna, is a peaceful riverside village with ancient '
               'temples and hills on every side.',
               'We visit the temples, take a boat ride when available, and camp by the water with a campfire, dinner '
               'and a sky full of stars.'],
         highlights=['Riverside camping on the Krishna backwaters', 'Someshwara temple complex',
                     'Boat ride when operating', 'Campfire and stargazing'],
         stops=[('Day 1 · Temples and riverside', 'Visit the Somasila temples and ghats.'),
                ('Day 1 · Camp and campfire', 'Set up camp, dinner and campfire.'),
                ('Day 2 · Sunrise by the river', 'Morning on the backwaters.'),
                ('Day 2 · Breakfast and return', 'Pack up and head back.')]),

    dict(title='Vizag Colony – Camping', cat='camping', region='Nalgonda', km='Approx. 160 km',
         duration='Overnight (2 days, 1 night)', difficulty='Easy', best='October to February',
         venue='Vizag Colony, Nagarjuna Sagar backwaters, Nalgonda district',
         summary='Tents on the sand at Vizag Colony — sunset, campfire and sunrise on the Nagarjuna Sagar backwaters.',
         body=['Vizag Colony’s sandy shore on the Nagarjuna Sagar backwaters is one of the best beach-style camping '
               'spots near Hyderabad.',
               'Arrive for the sunset, enjoy a campfire and dinner by the water, sleep in tents and wake up to sunrise '
               'over the reservoir, with an optional boat ride.'],
         highlights=['Beach-style camping by the water', 'Sunset and sunrise over the backwaters',
                     'Campfire and dinner', 'Optional boat ride'],
         stops=[('Day 1 · Arrive and set up', 'Set up camp on the shore.'),
                ('Day 1 · Sunset and campfire', 'Sunset, dinner and campfire.'),
                ('Day 2 · Sunrise and boat ride', 'Sunrise and a boat ride when available.'),
                ('Day 2 · Breakfast and return', 'Pack up and head back.')]),

    dict(title='No Name – Camping', cat='camping', region='Location revealed after confirmation', km='Within a few hours of Hyderabad',
         duration='Overnight (2 days, 1 night)', difficulty='Easy', best='October to February',
         venue='Secret campsite — shared with confirmed guests',
         summary='A mystery campsite: we reveal the location only to confirmed guests. Just bring your sense of adventure.',
         body=['“No Name” is our surprise camping trip. The campsite is a quiet, uncrowded spot within a few hours of '
               'Hyderabad, and we only share where it is with confirmed guests.',
               'Expect tents, a campfire, good company, a dark sky full of stars and a sunrise walk in the morning.'],
         highlights=['Surprise location', 'Quiet, uncrowded campsite',
                     'Campfire and stargazing', 'Sunrise walk'],
         stops=[('Day 1 · Reveal and drive', 'The location is revealed and we head out.'),
                ('Day 1 · Camp and campfire', 'Set up camp, dinner and campfire.'),
                ('Day 2 · Sunrise walk', 'Morning walk around the campsite.'),
                ('Day 2 · Breakfast and return', 'Pack up and head back.')]),

    dict(title='UTM – Camping', cat='camping', region='Telangana', km='To be confirmed',
         duration='Overnight (2 days, 1 night)', difficulty='Easy', best='October to February',
         venue='UTM campsite, Telangana',
         summary='An overnight camp with tents, a campfire evening and a morning of outdoor activities.',
         body=['Spend a night outdoors with the GoHyderabad community at the UTM campsite. The plan is a relaxed '
               'evening of campfire, games and stargazing, a night in tents and a morning of outdoor activities.',
               'The team will share full details of the campsite and activities before the trip.'],
         highlights=['Overnight tent stay', 'Campfire and games', 'Stargazing', 'Morning outdoor activities'],
         stops=[('Day 1 · Arrive and set up camp', 'Check in and settle in.'),
                ('Day 1 · Campfire evening', 'Dinner, games and campfire.'),
                ('Day 2 · Morning activities', 'Outdoor activities after sunrise.'),
                ('Day 2 · Breakfast and return', 'Pack up and head back.')]),

    # ---------------- Adventure ----------------
    dict(title='UTM – Day', cat='adventure', region='Telangana', km='To be confirmed',
         duration='Full day', difficulty='Easy to moderate', best='October to February',
         venue='UTM, Telangana',
         summary='A full day of outdoor adventure activities with the GoHyderabad community.',
         body=['An action-packed day of outdoor activities at UTM. Expect a mix of adventure activities, team games '
               'and time outdoors, run with safety briefings and trained instructors.',
               'The team will share the full list of activities before the trip.'],
         highlights=['Outdoor adventure activities', 'Team games', 'Trained instructors', 'Great for groups and friends'],
         stops=[('Arrive and briefing', 'Safety briefing and warm-up.'),
                ('Morning activities', 'First round of adventure activities.'),
                ('Lunch', 'Lunch break.'),
                ('Afternoon activities', 'More activities before heading back.')]),

    dict(title='Koilsagar Dam – Trek & Rappelling', cat='adventure', region='Mahabubnagar', km='Approx. 140 km',
         duration='Full day', difficulty='Moderate', best='October to February',
         venue='Koilsagar Dam, Mahabubnagar district',
         summary='Trek the hills around Koilsagar reservoir and try rappelling down a rock face with instructors.',
         body=['Koilsagar Dam, built in the 1940s on the Peddavagu stream, sits in a bowl of rocky hills in '
               'Mahabubnagar district. The granite faces around the reservoir are ideal for adventure activities.',
               'The day combines a hill trek with views of the reservoir and a rappelling session on a natural rock '
               'face, run by trained instructors with full safety gear. No experience needed.'],
         highlights=['Hill trek around the reservoir', 'Rappelling on natural rock',
                     'Trained instructors and safety gear', 'Beginners welcome'],
         stops=[('Arrive at Koilsagar', 'Briefing and warm-up.'),
                ('Hill trek', 'Trek with reservoir views.'),
                ('Rappelling session', 'Instructor-led rappelling with full safety gear.'),
                ('Lunch and sunset', 'Relax by the reservoir before heading back.')],
         faqs=[('Do I need climbing experience?', 'No. Instructors explain everything and you are on a safety rope at all times.')]),

    # ---------------- Rides ----------------
    dict(title='Pocharam – Ride', cat='rides', region='Medak / Kamareddy', km='Approx. 115 km',
         duration='Full day', difficulty='Riders with highway experience', best='October to February',
         venue='Pocharam Wildlife Sanctuary and Dam, Medak / Kamareddy',
         summary='A group bike ride to the Nizam-era Pocharam dam and its wildlife sanctuary.',
         body=['Pocharam Lake was created by a dam built in the Nizam era, and the forest around it is now the '
               'Pocharam Wildlife Sanctuary, home to deer, birds and migratory waterfowl in winter.',
               'This group ride covers smooth highways and countryside roads, with stops at the dam, the lake and the '
               'sanctuary, ridden at a safe group pace with a lead and sweep rider.'],
         highlights=['Group ride on scenic highways', 'Nizam-era Pocharam dam and lake',
                     'Wildlife sanctuary and birdlife', 'Lead and sweep riders'],
         stops=[('Ride briefing', 'Meet, bike check and ride briefing.'),
                ('Breakfast stop', 'Breakfast on the highway.'),
                ('Pocharam dam and lake', 'Views, photos and rest.'),
                ('Sanctuary and ride back', 'Sanctuary stop and the ride home.')],
         extra_bring=['A valid driving licence and vehicle papers.', 'A full-face helmet and riding gear.']),

    dict(title='Medak Bike Ride', cat='rides', region='Medak', km='Approx. 100 km',
         duration='Full day', difficulty='Riders with highway experience', best='October to February',
         venue='Medak Cathedral and Medak Fort, Medak',
         summary='Ride to Medak for the grand Medak Cathedral, the hilltop Medak Fort and the countryside on the way.',
         body=['Medak Cathedral, completed in 1924, is one of the largest churches in Asia, with soaring Gothic '
               'arches and stained-glass windows. Medak Fort, on a hill above the town, dates back to the Kakatiya era.',
               'The ride passes the Narsapur forest on the way, with a safe group pace and stops for breakfast, the '
               'cathedral and the fort.'],
         highlights=['Medak Cathedral — one of Asia’s largest churches', 'Kakatiya-era Medak Fort',
                     'Ride past the Narsapur forest', 'Group ride with lead and sweep riders'],
         stops=[('Ride briefing', 'Meet, bike check and ride briefing.'),
                ('Breakfast stop', 'Breakfast on the way.'),
                ('Medak Cathedral', 'Visit the cathedral.'),
                ('Medak Fort and ride back', 'Fort visit and the ride home.')],
         extra_bring=['A valid driving licence and vehicle papers.', 'A full-face helmet and riding gear.']),

    # ---------------- Lakes ----------------
    dict(title='Koil Sagar', cat='lakes', region='Mahabubnagar', km='Approx. 140 km',
         duration='Full day', difficulty='Easy', best='August to February',
         venue='Koilsagar Dam, Mahabubnagar district',
         summary='A reservoir ringed by rocky hills — easy walks, views and a calm sunset by the water.',
         body=['Koilsagar Dam was built in the 1940s on the Peddavagu stream. The reservoir is surrounded by rocky '
               'hills and is at its most beautiful after the monsoon, when the water is high.',
               'An easy day of walks, viewpoints and relaxing by the water.'],
         highlights=['Reservoir among rocky hills', 'Easy walks and viewpoints', 'Peaceful and uncrowded', 'Sunset by the water'],
         stops=[('Arrive at Koilsagar', 'Settle in by the dam.'),
                ('Walk and viewpoints', 'Easy walk to the viewpoints.'),
                ('Lunch', 'Lunch in the area.'),
                ('Sunset', 'Relax by the water before heading back.')]),

    dict(title='Laknavaram Lake', cat='lakes', region='Mulugu', km='Approx. 210 km',
         duration='Full day', difficulty='Easy', best='August to February',
         venue='Laknavaram Lake, Govindaraopet, Mulugu district',
         summary='A Kakatiya-era lake with islands, a hanging bridge and boating, surrounded by forest.',
         body=['Laknavaram Lake was built by the Kakatiya rulers in the 13th century. Today it is famous for its '
               'suspension bridge connecting small islands, its boating and the forested hills all around.',
               'Spend the day crossing the hanging bridge, boating on the lake and relaxing on the islands. Often '
               'combined with the Ramappa Temple (a UNESCO World Heritage Site) nearby.'],
         highlights=['13th-century Kakatiya lake', 'Hanging bridge across the islands',
                     'Boating', 'Forest and hill views'],
         stops=[('Arrive at Laknavaram', 'Walk across the hanging bridge.'),
                ('Boating', 'Boat ride on the lake, when operating.'),
                ('Lunch', 'Lunch by the lake.'),
                ('Islands and sunset', 'Time on the islands before heading back.')]),

    dict(title='Nagarjuna Sagar', cat='lakes', region='Nalgonda', km='Approx. 150 km',
         duration='Full day', difficulty='Easy', best='August to February',
         venue='Nagarjuna Sagar, Nalgonda district',
         summary='One of the world’s largest masonry dams, a boat to the Nagarjunakonda island museum, and Ethipothala Falls.',
         body=['Nagarjuna Sagar Dam on the Krishna river is one of the largest masonry dams in the world. The '
               'reservoir hides an island, Nagarjunakonda, where the remains of an ancient Buddhist settlement were '
               'moved and preserved in a museum.',
               'The day covers the dam, a boat ride to Nagarjunakonda when operating, and the nearby Ethipothala '
               'waterfall.'],
         highlights=['One of the world’s largest masonry dams', 'Boat to the Nagarjunakonda island museum',
                     'Ancient Buddhist heritage', 'Ethipothala waterfall nearby'],
         stops=[('Nagarjuna Sagar Dam', 'Views of the dam and the river.'),
                ('Nagarjunakonda', 'Boat ride to the island museum, when operating.'),
                ('Lunch', 'Lunch in the area.'),
                ('Ethipothala Falls', 'Visit the falls before heading back.')]),

    dict(title='Jurala Dam', cat='lakes', region='Jogulamba Gadwal', km='Approx. 180 km',
         duration='Full day', difficulty='Easy', best='August to January',
         venue='Priyadarshini Jurala Project, Jogulamba Gadwal district',
         summary='The Krishna river’s first dam in Telangana, with wide reservoir views and the Jogulamba temple nearby.',
         body=['The Priyadarshini Jurala Project is the first dam on the Krishna river after it enters Telangana. When '
               'the gates are open after the monsoon, the water rushing through is a sight to see.',
               'The day can be combined with Alampur’s Jogulamba temple, one of the Shakti Peethas, and the ancient '
               'Navabrahma temples.'],
         highlights=['First Krishna dam in Telangana', 'Gates-open views after the monsoon',
                     'Jogulamba temple, Alampur', 'Ancient Navabrahma temples'],
         stops=[('Jurala Dam', 'Dam and reservoir viewpoints.'),
                ('Lunch', 'Lunch in the area.'),
                ('Alampur temples', 'Jogulamba and Navabrahma temples.'),
                ('Head back', 'Return to Hyderabad.')]),

    dict(title='Kotpally Reservoir', cat='lakes', region='Vikarabad', km='Approx. 90 km',
         duration='Full day', difficulty='Easy', best='August to February',
         venue='Kotpally Reservoir, Vikarabad district',
         summary='Boating and kayaking on a quiet reservoir near Ananthagiri Hills.',
         body=['Kotpally Reservoir, near Vikarabad and Ananthagiri Hills, is a calm stretch of water popular for '
               'boating and kayaking. Low hills and farmland surround it.',
               'Spend the day on the water and pair it with a short visit to Ananthagiri.'],
         highlights=['Boating and kayaking', 'Quiet reservoir among low hills',
                     'Close to Ananthagiri Hills', 'Easy, relaxing day'],
         stops=[('Arrive at Kotpally', 'Settle in by the reservoir.'),
                ('Kayaking / boating', 'Time on the water, when operating.'),
                ('Lunch', 'Lunch in the area.'),
                ('Ananthagiri (optional)', 'Short visit before heading back.')]),

    dict(title='Vizag Colony Backwaters', cat='lakes', region='Nalgonda', km='Approx. 160 km',
         duration='Full day', difficulty='Easy', best='August to February',
         venue='Vizag Colony, Nagarjuna Sagar backwaters, Nalgonda district',
         summary='Sandy shores and boat rides on the vast Nagarjuna Sagar backwaters.',
         body=['The backwaters of Nagarjuna Sagar stretch for kilometres around Vizag Colony, a fishing village with a '
               'wide sandy shore.',
               'Take a boat out with the local fishermen when available, relax on the shore and stay for one of the '
               'best sunsets near Hyderabad.'],
         highlights=['Vast backwater views', 'Boat rides with local fishermen', 'Sandy shore', 'Sunset over the water'],
         stops=[('Arrive at Vizag Colony', 'Settle in by the water.'),
                ('Boat ride', 'Ride on the backwaters, when available.'),
                ('Lunch', 'Local lunch.'),
                ('Sunset', 'Sunset before heading back.')]),

    dict(title='Kondapochamma Lake', cat='lakes', region='Siddipet', km='Approx. 60 km',
         duration='Half day', difficulty='Easy', best='All year',
         venue='Kondapochamma Sagar, Markook, Siddipet district',
         summary='A huge new reservoir of the Kaleshwaram project, with wide views and sunsets close to the city.',
         body=['Kondapochamma Sagar, in Siddipet district, is one of the reservoirs of the Kaleshwaram lift '
               'irrigation project, opened in 2020. The bund offers wide views over a huge sheet of water.',
               'It is close enough for an easy half-day trip, best timed for sunset.'],
         highlights=['Part of the Kaleshwaram project', 'Wide views from the bund',
                     'Close to Hyderabad', 'Great sunset spot'],
         stops=[('Drive to Kondapochamma', 'Short drive out of the city.'),
                ('Reservoir bund', 'Walk along the bund.'),
                ('Sunset', 'Watch the sunset over the water.'),
                ('Head back', 'Return to Hyderabad.')]),

    # ---------------- Waterfalls ----------------
    dict(title='Mallela Theertham', cat='waterfalls', region='Nagarkurnool (Nallamala)', km='Approx. 175 km',
         duration='Full day', difficulty='Moderate', best='August to January',
         venue='Mallela Theertham, Amrabad Tiger Reserve, Nallamala forest',
         summary='A forest waterfall deep in the Nallamala, reached by a long flight of steps through the tiger reserve.',
         body=['Mallela Theertham is a waterfall hidden in the Nallamala forest inside the Amrabad Tiger Reserve, on '
               'the way to Srisailam. A long flight of steps leads down through the forest to a pool where the falls '
               'drop over the rocks.',
               'It is at its best after the monsoon. Forest timings apply, and the climb back up is a good workout.'],
         highlights=['Waterfall in the Nallamala forest', 'Inside the Amrabad Tiger Reserve',
                     'Steps down through the forest', 'Natural rock pool'],
         stops=[('Drive through Nallamala', 'Scenic forest drive.'),
                ('Steps to the falls', 'Walk down to the waterfall.'),
                ('Waterfall', 'Time at the falls.'),
                ('Climb back and return', 'Climb back up and head home.')],
         faqs=[('Are there forest timings?', 'Yes. The area is inside a tiger reserve, so entry and exit follow forest '
                'department timings and rules.')]),

    dict(title='Kuntala Falls', cat='waterfalls', region='Nirmal / Adilabad', km='Approx. 260 km',
         duration='Full day (long drive)', difficulty='Easy to moderate', best='August to December',
         venue='Kuntala Falls, Neredigonda, Nirmal district',
         summary='Telangana’s highest waterfall, where the Kadam river drops in two tiers through the forest.',
         body=['Kuntala Falls on the Kadam river is the highest waterfall in Telangana. The river falls in tiers over a '
               'rocky gorge surrounded by forest, and the spot is linked in local legend with Shakuntala of the '
               'Mahabharata.',
               'Visit after the monsoon to see the falls at full flow. Steps lead down to the viewing area.'],
         highlights=['Highest waterfall in Telangana', 'Tiered falls in a forest gorge',
                     'Best after the monsoon', 'Can be combined with Pochera Falls'],
         stops=[('Kuntala Falls', 'Walk down to the falls.'),
                ('Lunch', 'Lunch in the area.'),
                ('Pochera Falls (optional)', 'Second waterfall nearby.'),
                ('Head back', 'Long drive back to Hyderabad.')]),

    dict(title='Ethipothala Falls', cat='waterfalls', region='Palnadu, Andhra Pradesh', km='Approx. 165 km',
         duration='Full day', difficulty='Easy', best='August to January',
         venue='Ethipothala Falls, near Nagarjuna Sagar',
         summary='The Chandravanka stream plunges into a gorge near Nagarjuna Sagar — with a crocodile breeding centre below.',
         body=['Ethipothala Falls is formed where the Chandravanka stream drops into a rocky gorge before joining the '
               'Krishna, a few kilometres from Nagarjuna Sagar. Viewpoints overlook the falls and the pool below, '
               'which is a crocodile breeding area.',
               'Combine it with Nagarjuna Sagar Dam for a full day out.'],
         highlights=['Waterfall into a rocky gorge', 'Viewpoints over the falls',
                     'Crocodile breeding pool', 'Close to Nagarjuna Sagar'],
         stops=[('Ethipothala Falls', 'Viewpoints and the falls.'),
                ('Lunch', 'Lunch in the area.'),
                ('Nagarjuna Sagar Dam', 'Dam views.'),
                ('Head back', 'Return to Hyderabad.')]),

    dict(title='Bheemuni Paadam Waterfalls', cat='waterfalls', region='Mahabubabad (near Warangal)', km='Approx. 200 km',
         duration='Full day', difficulty='Easy to moderate', best='August to January',
         venue='Bheemuni Paadam, Gudur mandal, Mahabubabad district',
         summary='A forest waterfall named after a giant footprint-shaped rock linked to Bheema of the Mahabharata.',
         body=['Bheemuni Paadam is a waterfall in the forests of Mahabubabad district, about an hour from Warangal. '
               'Its name means “Bheema’s footprint”, after a large footprint-shaped rock that local legend links to '
               'Bheema.',
               'The falls are at their best during and after the monsoon. Combine with Warangal’s Thousand Pillar '
               'Temple or Fort on the way.'],
         highlights=['Forest waterfall near Warangal', 'Legendary footprint-shaped rock',
                     'Best during and after the monsoon', 'Warangal heritage stop on the way'],
         stops=[('Bheemuni Paadam', 'Walk to the falls.'),
                ('Lunch', 'Lunch in the area.'),
                ('Warangal stop (optional)', 'Thousand Pillar Temple or Warangal Fort.'),
                ('Head back', 'Return to Hyderabad.')]),

    dict(title='Bogata Waterfall', cat='waterfalls', region='Mulugu', km='Approx. 330 km',
         duration='Full day (long drive) or overnight', difficulty='Easy', best='July to December',
         venue='Bogatha Waterfall, Cheekupally, Wazeedu mandal, Mulugu district',
         summary='The “Niagara of Telangana” — a wide waterfall in the forests of Mulugu district.',
         body=['Bogatha Waterfall near Wazeedu in Mulugu district is often called the Niagara of Telangana for its '
               'wide curtain of water. It sits in thick forest close to the Chhattisgarh border.',
               'It is a long way from Hyderabad but worth it after the monsoon. Swimming is restricted to marked '
               'areas, and forest rules apply.'],
         highlights=['“Niagara of Telangana”', 'Wide curtain of water in thick forest',
                     'Best in and after the monsoon', 'Remote and beautiful'],
         stops=[('Drive to Wazeedu', 'Long scenic drive.'),
                ('Bogatha Waterfall', 'Time at the falls.'),
                ('Lunch', 'Lunch in the area.'),
                ('Head back', 'Return journey.')]),

    dict(title='Muthyamdhara Waterfalls', cat='waterfalls', region='Mulugu', km='Approx. 300 km',
         duration='Full day (long drive) or overnight', difficulty='Moderate to difficult', best='August to December',
         venue='Muthyamdhara Waterfalls, Veerabhadraram, Venkatapuram mandal, Mulugu district',
         summary='A forest trek to the “pearl stream” waterfall, deep in the hills of Mulugu district.',
         body=['Muthyamdhara — “stream of pearls” — is a tall waterfall in the forested hills near Veerabhadraram in '
               'Mulugu district. It is reached by a trek through forest and streams, which keeps the crowds away.',
               'A trip for people who enjoy a proper trek, best done after the monsoon. Forest rules apply.'],
         highlights=['Tall forest waterfall', 'Forest trek with stream crossings',
                     'Remote and uncrowded', 'Best after the monsoon'],
         stops=[('Arrive at Veerabhadraram', 'Briefing and start of the trek.'),
                ('Forest trek', 'Trek through forest and streams.'),
                ('Muthyamdhara falls', 'Time at the waterfall.'),
                ('Trek back and return', 'Walk back and head home.')]),

    # ---------------- Wildlife ----------------
    dict(title='Tadoba-Andhari Tiger Reserve', cat='wildlife', region='Chandrapur, Maharashtra', km='Approx. 430 km',
         duration='2–3 days', difficulty='Easy', best='October to June (core zones close in the monsoon)',
         venue='Tadoba-Andhari Tiger Reserve, Chandrapur, Maharashtra',
         summary='Jungle safaris in one of India’s best tiger reserves, famous for frequent tiger sightings.',
         body=['Tadoba-Andhari is Maharashtra’s oldest and largest national park and one of the best places in India '
               'to see wild tigers. Teak forests, lakes and meadows are also home to leopards, sloth bears, gaur, '
               'wild dogs and many birds.',
               'The trip includes open-jeep safaris in the reserve (subject to permits and availability) and a stay '
               'near the park gates.'],
         highlights=['Among India’s best tiger-sighting reserves', 'Open-jeep jungle safaris',
                     'Leopards, sloth bears, gaur and wild dogs', 'Stay near the forest'],
         stops=[('Day 1 · Travel to Tadoba', 'Journey to Chandrapur and check in.'),
                ('Day 2 · Morning safari', 'Early jungle safari.'),
                ('Day 2 · Evening safari', 'Afternoon safari, subject to permits.'),
                ('Day 3 · Return', 'Head back to Hyderabad.')],
         faqs=[('Are tiger sightings guaranteed?', 'No. Tadoba has excellent sighting rates, but wildlife sightings are never guaranteed.')]),

    dict(title='Pench – Day Safari', cat='wildlife', region='Seoni, Madhya Pradesh', km='Approx. 600 km (via Nagpur)',
         duration='2–3 days', difficulty='Easy', best='October to June (core zones close in the monsoon)',
         venue='Pench Tiger Reserve, Madhya Pradesh',
         summary='Safaris in the teak forests of Pench — tigers, leopards and the landscapes of The Jungle Book.',
         body=['Pench Tiger Reserve straddles the Madhya Pradesh–Maharashtra border along the Pench river. Its teak '
               'forests and meadows are said to have inspired the setting of Rudyard Kipling’s The Jungle Book.',
               'The trip includes jeep safaris in the reserve (subject to permits) to look for tigers, leopards, wild '
               'dogs, deer and a rich variety of birds.'],
         highlights=['The Jungle Book landscapes', 'Jeep safaris in the reserve',
                     'Tigers, leopards and wild dogs', 'Rich birdlife along the Pench river'],
         stops=[('Day 1 · Travel to Pench', 'Journey via Nagpur and check in.'),
                ('Day 2 · Safari', 'Jungle safari, subject to permits.'),
                ('Day 2 · Evening', 'Relax near the forest.'),
                ('Day 3 · Return', 'Head back to Hyderabad.')],
         faqs=[('Are tiger sightings guaranteed?', 'No. Wildlife sightings are never guaranteed.')]),

    dict(title='Kinnerasani Dam & Wildlife Sanctuary', cat='wildlife', region='Bhadradri Kothagudem', km='Approx. 300 km',
         duration='Full day (long drive) or overnight', difficulty='Easy', best='October to February',
         venue='Kinnerasani Dam and Wildlife Sanctuary, Paloncha, Bhadradri Kothagudem district',
         summary='A forest reservoir with islands and a wildlife sanctuary, close to the temple town of Bhadrachalam.',
         body=['Kinnerasani Dam near Paloncha forms a large reservoir dotted with islands, surrounded by the '
               'Kinnerasani Wildlife Sanctuary. Deer, birds and other wildlife live in the forest around it.',
               'The trip includes the dam, the deer park and viewpoints, and can be combined with the Sri Sita Ramachandra '
               'Swamy temple at Bhadrachalam.'],
         highlights=['Reservoir with forested islands', 'Wildlife sanctuary and deer park',
                     'Boating when available', 'Bhadrachalam temple nearby'],
         stops=[('Kinnerasani Dam', 'Dam and reservoir views.'),
                ('Wildlife sanctuary', 'Deer park and forest.'),
                ('Lunch', 'Lunch in the area.'),
                ('Bhadrachalam (optional)', 'Temple visit before heading back.')]),

    # ---------------- Temples ----------------
    dict(title='Umamaheshwaram', cat='temples', region='Nagarkurnool (Nallamala)', km='Approx. 150 km',
         duration='Full day', difficulty='Easy to moderate', best='August to February',
         venue='Umamaheshwaram Temple, near Achampet, Nagarkurnool district',
         summary='A Shiva temple in the Nallamala hills, known as the northern gateway to Srisailam, with a natural spring.',
         body=['Umamaheshwaram, near Achampet, is an ancient Shiva temple tucked into the Nallamala hills. It is '
               'traditionally called the northern gateway of Srisailam, and a natural spring flows from the rock '
               'beside the shrine.',
               'The road climbs through forest to the temple, with lovely views of the hills. It can be combined with '
               'other stops on the Srisailam route.'],
         highlights=['Northern gateway of Srisailam', 'Natural spring beside the shrine',
                     'Nallamala forest setting', 'Hill views on the way'],
         stops=[('Drive into the Nallamala', 'Forest road up to the temple.'),
                ('Umamaheshwaram temple', 'Darshan and time at the spring.'),
                ('Lunch', 'Lunch in Achampet.'),
                ('Head back', 'Return to Hyderabad.')]),

    dict(title='Vemulawada', cat='temples', region='Rajanna Sircilla', km='Approx. 150 km',
         duration='Full day', difficulty='Easy', best='All year',
         venue='Sri Raja Rajeshwara Swamy Temple, Vemulawada',
         summary='The famous Sri Raja Rajeshwara Swamy Temple, one of the most visited Shiva temples in Telangana.',
         body=['Vemulawada is home to the Sri Raja Rajeshwara Swamy Temple, popularly called Dakshina Kashi. The '
               'temple complex dates back over a thousand years and draws pilgrims from across the state.',
               'The day includes darshan, the temple tank and the town, with an optional stop at the Lower Manair Dam '
               'or Karimnagar on the way.'],
         highlights=['Sri Raja Rajeshwara Swamy Temple', 'Known as Dakshina Kashi',
                     'Ancient temple complex and tank', 'Optional Karimnagar stop'],
         stops=[('Vemulawada temple', 'Darshan at the Raja Rajeshwara temple.'),
                ('Temple town', 'Temple tank and nearby shrines.'),
                ('Lunch', 'Lunch in Vemulawada.'),
                ('Head back', 'Return, with an optional Karimnagar stop.')],
         faqs=[('How long is darshan?', 'It depends on the crowd. Weekends and festivals can be very busy.')]),

    dict(title='Edupayala Vana Durga Bhavani Temple', cat='temples', region='Medak', km='Approx. 110 km',
         duration='Full day', difficulty='Easy', best='August to February',
         venue='Edupayala Vana Durga Bhavani Temple, Papannapet mandal, Medak district',
         summary='A Durga temple among rocks on the Manjira river, where seven streams are said to meet.',
         body=['Edupayala Vana Durga Bhavani Temple sits among rocks and forest on the Manjira river. “Edupayala” means '
               '“seven streams”, after the seven branches of the river that are said to meet here.',
               'The temple is especially lively during the Maha Shivaratri jatara. Combine it with Medak Cathedral and '
               'Medak Fort for a full day.'],
         highlights=['Temple on the Manjira river', 'Seven streams meeting among the rocks',
                     'Forest and river setting', 'Medak Cathedral nearby'],
         stops=[('Edupayala temple', 'Darshan and time by the river.'),
                ('Lunch', 'Lunch in the area.'),
                ('Medak Cathedral', 'Visit the cathedral.'),
                ('Head back', 'Return to Hyderabad.')]),

    dict(title='Damagundam Ramaklingeshwara Temple', cat='temples', region='Vikarabad', km='Approx. 75 km',
         duration='Full day', difficulty='Easy to moderate', best='August to February',
         venue='Damagundam Ramalingeshwara Temple, Pudur mandal, Vikarabad district',
         summary='A Shiva temple deep in the Damagundam forest, reached by a walk through the woods.',
         body=['The Ramalingeshwara Swamy temple at Damagundam stands inside a reserve forest in Vikarabad district, '
               'with a temple pond and dense trees all around. The forest is one of the largest green patches left '
               'close to Hyderabad.',
               'Walk through the woods to the temple and spend a calm day in nature.'],
         highlights=['Temple inside a reserve forest', 'Forest walk to the shrine',
                     'Temple pond', 'Close to Hyderabad'],
         stops=[('Arrive at Damagundam', 'Briefing at the forest edge.'),
                ('Forest walk', 'Walk through the woods to the temple.'),
                ('Ramalingeshwara temple', 'Darshan and time at the pond.'),
                ('Head back', 'Walk back and return to Hyderabad.')]),

    dict(title='Dharmapuri', cat='temples', region='Jagtial', km='Approx. 230 km',
         duration='Full day (long drive)', difficulty='Easy', best='All year',
         venue='Sri Lakshmi Narasimha Swamy Temple, Dharmapuri, Jagtial district',
         summary='A temple town on the Godavari, home to the Sri Lakshmi Narasimha Swamy Temple and river ghats.',
         body=['Dharmapuri, on the banks of the Godavari in Jagtial district, is an old temple town centred on the Sri '
               'Lakshmi Narasimha Swamy Temple. The Godavari here flows south-north, which is considered sacred, and '
               'the ghats are busy during Pushkaralu.',
               'The day includes the temple, the river ghats and the town.'],
         highlights=['Sri Lakshmi Narasimha Swamy Temple', 'Godavari river ghats',
                     'Historic temple town', 'Pushkaralu pilgrimage site'],
         stops=[('Dharmapuri temple', 'Darshan at the Narasimha temple.'),
                ('Godavari ghats', 'Time by the river.'),
                ('Lunch', 'Lunch in the town.'),
                ('Head back', 'Long drive back to Hyderabad.')]),

    # ---------------- Viewpoints ----------------
    dict(title='Octopus View Point', cat='viewpoints', region='Nagarkurnool (Nallamala)', km='Approx. 170 km',
         duration='Full day', difficulty='Easy', best='October to February',
         venue='Octopus View Point, near Domalapenta, Amrabad Tiger Reserve',
         summary='A bird’s-eye view of the Krishna backwaters spreading like an octopus’s arms through the Nallamala hills.',
         body=['Octopus View Point is a viewing deck inside the Amrabad Tiger Reserve, near the Domalapenta forest '
               'checkpost on the Hyderabad–Srisailam highway. From here the Krishna river winds around the hills in '
               'arms that look like an octopus’s tentacles.',
               'The day includes the Nallamala forest drive and other viewpoints on the Srisailam route. Mobile '
               'signal is limited beyond Mannanur, and forest timings apply.'],
         highlights=['Bird’s-eye view of the Krishna backwaters', 'Inside the Amrabad Tiger Reserve',
                     'Scenic Nallamala forest drive', 'Other viewpoints on the Srisailam route'],
         stops=[('Drive into the Nallamala', 'Forest drive past Mannanur.'),
                ('Octopus View Point', 'Views and photos.'),
                ('Lunch', 'Lunch on the route.'),
                ('Other viewpoints and return', 'More stops before heading back.')],
         faqs=[('Are there forest timings?', 'Yes. The viewpoint is inside a tiger reserve, so it follows forest department '
                'timings and may close by early evening.')]),
]
