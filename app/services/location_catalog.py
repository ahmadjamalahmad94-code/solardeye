"""Curated registration location catalog.

This is intentionally local and dependency-free so registration stays fast and does not
break if a third-party geo API is unavailable. It covers the main markets now and can
be expanded safely later.
"""

COUNTRY_CATALOG = [
    {"code":"PS","dial":"+970","name_ar":"فلسطين","name_en":"Palestine","timezone":"Asia/Hebron","cities_ar":["نابلس","رام الله","الخليل","غزة","جنين","طولكرم","بيت لحم","أريحا","قلقيلية","سلفيت","طوباس","القدس"],"cities_en":["Nablus","Ramallah","Hebron","Gaza","Jenin","Tulkarm","Bethlehem","Jericho","Qalqilya","Salfit","Tubas","Jerusalem"]},
    {"code":"JO","dial":"+962","name_ar":"الأردن","name_en":"Jordan","timezone":"Asia/Amman","cities_ar":["عمّان","إربد","الزرقاء","العقبة","السلط","مادبا","الكرك","المفرق","جرش","عجلون"],"cities_en":["Amman","Irbid","Zarqa","Aqaba","Salt","Madaba","Karak","Mafraq","Jerash","Ajloun"]},
    {"code":"SA","dial":"+966","name_ar":"السعودية","name_en":"Saudi Arabia","timezone":"Asia/Riyadh","cities_ar":["الرياض","جدة","الدمام","مكة","المدينة","الخبر","الطائف","تبوك","بريدة","أبها"],"cities_en":["Riyadh","Jeddah","Dammam","Makkah","Madinah","Khobar","Taif","Tabuk","Buraydah","Abha"]},
    {"code":"AE","dial":"+971","name_ar":"الإمارات","name_en":"United Arab Emirates","timezone":"Asia/Dubai","cities_ar":["دبي","أبوظبي","الشارقة","عجمان","العين","رأس الخيمة","الفجيرة"],"cities_en":["Dubai","Abu Dhabi","Sharjah","Ajman","Al Ain","Ras Al Khaimah","Fujairah"]},
    {"code":"EG","dial":"+20","name_ar":"مصر","name_en":"Egypt","timezone":"Africa/Cairo","cities_ar":["القاهرة","الإسكندرية","الجيزة","المنصورة","طنطا","أسيوط","الأقصر","أسوان","السويس","بورسعيد"],"cities_en":["Cairo","Alexandria","Giza","Mansoura","Tanta","Asyut","Luxor","Aswan","Suez","Port Said"]},
    {"code":"TR","dial":"+90","name_ar":"تركيا","name_en":"Turkey","timezone":"Europe/Istanbul","cities_ar":["إسطنبول","أنقرة","إزمير","بورصة","أنطاليا","قونية","غازي عنتاب"],"cities_en":["Istanbul","Ankara","Izmir","Bursa","Antalya","Konya","Gaziantep"]},
    {"code":"QA","dial":"+974","name_ar":"قطر","name_en":"Qatar","timezone":"Asia/Qatar","cities_ar":["الدوحة","الوكرة","الريان","الخور"],"cities_en":["Doha","Al Wakrah","Al Rayyan","Al Khor"]},
    {"code":"KW","dial":"+965","name_ar":"الكويت","name_en":"Kuwait","timezone":"Asia/Kuwait","cities_ar":["مدينة الكويت","حولي","الفروانية","الأحمدي","الجهراء"],"cities_en":["Kuwait City","Hawalli","Farwaniya","Ahmadi","Jahra"]},
    {"code":"BH","dial":"+973","name_ar":"البحرين","name_en":"Bahrain","timezone":"Asia/Bahrain","cities_ar":["المنامة","المحرق","الرفاع","مدينة عيسى"],"cities_en":["Manama","Muharraq","Riffa","Isa Town"]},
    {"code":"OM","dial":"+968","name_ar":"عُمان","name_en":"Oman","timezone":"Asia/Muscat","cities_ar":["مسقط","صلالة","صحار","نزوى","صور"],"cities_en":["Muscat","Salalah","Sohar","Nizwa","Sur"]},
    {"code":"IQ","dial":"+964","name_ar":"العراق","name_en":"Iraq","timezone":"Asia/Baghdad","cities_ar":["بغداد","البصرة","أربيل","الموصل","النجف","كربلاء"],"cities_en":["Baghdad","Basra","Erbil","Mosul","Najaf","Karbala"]},
    {"code":"LB","dial":"+961","name_ar":"لبنان","name_en":"Lebanon","timezone":"Asia/Beirut","cities_ar":["بيروت","طرابلس","صيدا","صور","زحلة"],"cities_en":["Beirut","Tripoli","Sidon","Tyre","Zahle"]},
    {"code":"SY","dial":"+963","name_ar":"سوريا","name_en":"Syria","timezone":"Asia/Damascus","cities_ar":["دمشق","حلب","حمص","اللاذقية","حماة"],"cities_en":["Damascus","Aleppo","Homs","Latakia","Hama"]},
    {"code":"MA","dial":"+212","name_ar":"المغرب","name_en":"Morocco","timezone":"Africa/Casablanca","cities_ar":["الدار البيضاء","الرباط","مراكش","فاس","طنجة","أكادير"],"cities_en":["Casablanca","Rabat","Marrakesh","Fes","Tangier","Agadir"]},
    {"code":"DZ","dial":"+213","name_ar":"الجزائر","name_en":"Algeria","timezone":"Africa/Algiers","cities_ar":["الجزائر","وهران","قسنطينة","عنابة","سطيف"],"cities_en":["Algiers","Oran","Constantine","Annaba","Setif"]},
    {"code":"TN","dial":"+216","name_ar":"تونس","name_en":"Tunisia","timezone":"Africa/Tunis","cities_ar":["تونس","صفاقس","سوسة","القيروان","بنزرت"],"cities_en":["Tunis","Sfax","Sousse","Kairouan","Bizerte"]},
    {"code":"LY","dial":"+218","name_ar":"ليبيا","name_en":"Libya","timezone":"Africa/Tripoli","cities_ar":["طرابلس","بنغازي","مصراتة","سبها"],"cities_en":["Tripoli","Benghazi","Misrata","Sabha"]},
    {"code":"YE","dial":"+967","name_ar":"اليمن","name_en":"Yemen","timezone":"Asia/Aden","cities_ar":["صنعاء","عدن","تعز","الحديدة","إب"],"cities_en":["Sana'a","Aden","Taiz","Hodeidah","Ibb"]},
    {"code":"SD","dial":"+249","name_ar":"السودان","name_en":"Sudan","timezone":"Africa/Khartoum","cities_ar":["الخرطوم","أم درمان","بورتسودان","كسلا"],"cities_en":["Khartoum","Omdurman","Port Sudan","Kassala"]},
    {"code":"US","dial":"+1","name_ar":"الولايات المتحدة","name_en":"United States","timezone":"America/New_York","cities_ar":["نيويورك","لوس أنجلوس","شيكاغو","هيوستن","ميامي","سان فرانسيسكو"],"cities_en":["New York","Los Angeles","Chicago","Houston","Miami","San Francisco"]},
    {"code":"GB","dial":"+44","name_ar":"المملكة المتحدة","name_en":"United Kingdom","timezone":"Europe/London","cities_ar":["لندن","مانشستر","برمنغهام","ليفربول","ليدز"],"cities_en":["London","Manchester","Birmingham","Liverpool","Leeds"]},
    {"code":"DE","dial":"+49","name_ar":"ألمانيا","name_en":"Germany","timezone":"Europe/Berlin","cities_ar":["برلين","ميونخ","هامبورغ","فرانكفورت","كولونيا"],"cities_en":["Berlin","Munich","Hamburg","Frankfurt","Cologne"]},
    {"code":"FR","dial":"+33","name_ar":"فرنسا","name_en":"France","timezone":"Europe/Paris","cities_ar":["باريس","مارسيليا","ليون","تولوز","نيس"],"cities_en":["Paris","Marseille","Lyon","Toulouse","Nice"]},
    {"code":"IT","dial":"+39","name_ar":"إيطاليا","name_en":"Italy","timezone":"Europe/Rome","cities_ar":["روما","ميلانو","نابولي","تورينو","فلورنسا"],"cities_en":["Rome","Milan","Naples","Turin","Florence"]},
    {"code":"ES","dial":"+34","name_ar":"إسبانيا","name_en":"Spain","timezone":"Europe/Madrid","cities_ar":["مدريد","برشلونة","فالنسيا","إشبيلية","ملقة"],"cities_en":["Madrid","Barcelona","Valencia","Seville","Malaga"]},
    {"code":"OTHER","dial":"+","name_ar":"دولة أخرى","name_en":"Other country","timezone":"UTC","cities_ar":["مدينة أخرى"],"cities_en":["Other city"]},
]

TIMEZONE_OPTIONS = sorted({c["timezone"] for c in COUNTRY_CATALOG} | {"UTC","Asia/Hebron","Asia/Jerusalem","Europe/London","America/New_York"})

def countries_for_template():
    return COUNTRY_CATALOG

def timezones_for_template():
    return TIMEZONE_OPTIONS

def find_country(code_or_name: str):
    needle = (code_or_name or "").strip().lower()
    if not needle:
        return None
    for c in COUNTRY_CATALOG:
        if needle in {c["code"].lower(), c["name_ar"].lower(), c["name_en"].lower()}:
            return c
    return None
