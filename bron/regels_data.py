"""Inhoud van regeltemplate v4 (AGV Waterschapsverordening, art. 2.15 en 3.14-3.18).

Dit bestand is de bron waaruit maak_template.py het Excel-bestand bouwt.
Na de eerste oplevering is het Excel-bestand de plek om regels te beheren.
"""

ZONES = [
    # code, keringtype, zone, omschrijving
    ("WK-KZ", "waterkerend", "kernzone", "Kernzone van een waterkerend dijklichaam"),
    ("WK-BZ", "waterkerend", "beschermingszone", "Beschermingszone van een waterkerend dijklichaam"),
    ("WK-BBZ", "waterkerend", "buitenbeschermingszone", "Buitenbeschermingszone van een waterkerend dijklichaam"),
    ("HV-KZ", "half-verholen", "kernzone", "Kernzone van een half-verholen waterkering"),
    ("HV-BZ", "half-verholen", "beschermingszone", "Beschermingszone van een half-verholen waterkering"),
    ("HV-BBZ", "half-verholen", "buitenbeschermingszone", "Beschermingszone half-verholen waterkering buitendijks (legger laag 18)"),
    ("VH-KZ", "verholen", "kernzone", "Kernzone van een verholen waterkering"),
    ("VH-BZ", "verholen", "beschermingszone", "Beschermingszone van een verholen waterkering"),
    ("VH-BBZ", "verholen", "buitenbeschermingszone", "Buitenbeschermingszone van een verholen waterkering (geen kabelregels in WSV)"),
]
ZONE_CODES = [z[0] for z in ZONES]

GEO_LAGEN = [
    # naam, bron, gebruik
    ("zones", "data_AGV/Legger_verwerkt/Alle_keringen/Zones_alle_keringen.shp (velden dijktype, zone, code)", "Bepaalt per tracédeel de zone"),
    ("referentielijn", "data_AGV/Legger_verwerkt/Alle_keringen/Referentielijnen_alle_keringen.shp", "Hoek met de kering, kruisen van de referentielijn"),
    ("kruin", "data_AGV/kruinlagen/19_kruin_waterkerend, 20_kruin_half_verholen, 21_kruin_verholen", "raakt_kruin en dwars_door_kruin"),
]

PARAMETERS = [
    # naam, waarde, eenheid, toelichting
    ("HOEK_MIN", 75, "graden", "Minimale hoek tussen tracé en kering om als 'loodrecht' te gelden (90 = precies haaks)."),
    ("DWARS_AANDEEL", 0.75, "fractie", "Deel van de zonebreedte (haaks op de referentielijn) dat het tracé moet overbruggen om als 'dwars door' te gelden."),
    ("DRUKLEIDING_GRENS_BAR", 1.0, "bar", "Boven deze druk is een leiding een drukleiding of drukriolering (afspraak Nico 28-10)."),
    ("SNAP_AFSTAND_M", 0.5, "meter", "Tracédelen korter dan dit worden samengevoegd met het buurdeel (ruis bij zonegrenzen)."),
]

# veld, vraag, type, waarden, eenheid, nodig_bij, bron_tekening
INVOERVELDEN = [
    ("type", "Gaat het om een kabel, leiding of mantelbuis?", "keuze", "kabel; leiding; mantelbuis", "", "altijd", "NLCS-laag en legenda"),
    ("doel", "Wat is het doel van het tracé?", "keuze", "huisaansluiting; distributie", "", "altijd", "Afgeleid uit lengte en aansluiting op pand; vergunningverlener bevestigt"),
    ("werkwijze", "Welke werkwijze?", "keuze", "nieuw; vervangen; verwijderen; volschuimen; achterlaten; blazen; spoed_reparatie; lasgat; proefsleuf", "", "altijd", "NLCS-prefix N/V, labels 'te verwijderen', 'volschuimen', 'blazen' en samenvatting. volschuimen = leiding blijft liggen en wordt volgeschuimd; achterlaten = blijft liggen zonder volschuimen"),
    ("boormethode", "Welke aanlegmethode?", "keuze", "geen; gestuurde_boring; boogzinker; boogboring; nano_drill; raketboring", "", "altijd", "Labels en symbolen (HDD, boogzinker); 'geen' = open ontgraving"),
    ("medium", "Welk medium gaat door de leiding?", "keuze", "gas; drinkwater; hwa; dwa; olie; overig", "", "type == leiding", "NLCS-discipline (RI, DW, G)"),
    ("kabelsoort", "Welke soort kabel?", "keuze", "laagspanning; middenspanning; hoogspanning; telecom", "", "type == kabel", "NLCS-laag en labels"),
    ("ontgravingsdiepte_m", "Hoe diep ligt de onderkant van de buis of kabel onder maaiveld?", "getal", ">0", "m", "altijd", "Dekking/BOK-labels; onderkant buis, bij beton wanddikte optellen (afspraak 28-10)"),
    ("druk_bar", "Wat is de werkdruk in de leiding?", "getal", ">=0", "bar", "type == leiding", "Zelden op tekening"),
    ("diameter_mm", "Wat is de uitwendige diameter?", "getal", ">0", "mm", "type in (leiding, mantelbuis)", "Labels zoals 'Ø110'"),
    ("materiaal", "Welk materiaal?", "keuze", "PE; PVC; PP; staal; AC; beton; gres; koper; GVK", "", "type == leiding", "Labels zoals 'PE'"),
    ("sdr", "Welke SDR-klasse heeft de leiding?", "getal", ">0", "", "materiaal == PE", "Labels zoals 'SDR11'"),
    ("kwelscherm_kleikist", "Wordt een kwelscherm met kleikist aangebracht?", "keuze", "ja; nee", "", "huisaansluiting die de kruin raakt", "Detailtekening"),
    ("kruist_teensloot", "Kruist het tracé een teensloot?", "keuze", "ja; nee", "", "huisaansluiting in WK-KZ/WK-BZ", "BGT-waterdeel of tekening"),
    ("afstand_binnenteen_m", "Hoe ver ligt de kabel van de binnenteen van de dijk?", "getal", ">=0", "m", "kabel in WK-BZ", "Niet in legger; tekening of vergunningverlener"),
    ("boordiepte_onder_kruin_m", "Hoe diep ligt de boring onder de kruinhoogte?", "getal", ">=0", "m", "gestuurde boring", "Boorprofiel; kruinhoogte uit referentielijn of AHN"),
    ("diepte_onder_pleistoceen_m", "Hoe ver ligt de boring onder de bovenkant van het vaste pleistocene zand?", "getal", ">=0", "m", "gestuurde boring onder WK/HV, alleen als boordiepte < 10 m", "Boorprofiel/sondering"),
]

# naam, definitie, formule, bron
BEGRIPPEN = [
    ("is_kabel", "Het tracédeel is een kabel", 'type == "kabel"', "invoer"),
    ("is_leiding", "Het tracédeel is een leiding die een medium voert", 'type == "leiding"', "invoer"),
    ("is_mantelbuis", "Lege buis waar een kabel of leiding doorheen gaat; geen medium, geen druk", 'type == "mantelbuis"', "invoer"),
    ("is_huisaansluiting", "Aansluiting van één pand", 'doel == "huisaansluiting"', "invoer"),
    ("is_aanleg", "Aanleggen of vernieuwen", 'werkwijze in ("nieuw", "vervangen")', "invoer"),
    ("is_verwijderen", "Verwijderen; vervangen telt ook als verwijderen", 'werkwijze in ("verwijderen", "vervangen")', "invoer"),
    ("is_achterlaten", "Buiten gebruik gestelde leiding blijft in de grond (wel of niet volgeschuimd)", 'werkwijze in ("volschuimen", "achterlaten")', "invoer"),
    ("is_318", "Valt onder art. 3.18 (spoed, lasgat, proefsleuf, blazen; afspraak Nico 28-10)", 'werkwijze in ("spoed_reparatie", "lasgat", "proefsleuf", "blazen")', "invoer"),
    ("is_215_lid5", "Uitzondering 2.15 lid 5 (lid 2 en 3 gelden niet)", 'werkwijze in ("spoed_reparatie", "lasgat", "proefsleuf", "blazen")', "invoer"),
    ("open_ontgraving", "Aanleg in open sleuf", 'boormethode == "geen"', "invoer"),
    ("gestuurde_boring", "Aanleg met gestuurde boring (art. 3.16)", 'boormethode == "gestuurde_boring"', "invoer"),
    ("is_drukleiding", "Leiding met druk boven de grens (persleiding)", "is_leiding AND druk_bar > DRUKLEIDING_GRENS_BAR", "invoer + parameter"),
    ("is_drinkwater", "Drinkwaterleiding", 'is_leiding AND medium == "drinkwater"', "invoer"),
    ("is_gas", "Gasleiding", 'is_leiding AND medium == "gas"', "invoer"),
    ("is_vrijverval_riool", "Rioolleiding onder vrij verval", 'is_leiding AND medium in ("hwa", "dwa") AND druk_bar <= DRUKLEIDING_GRENS_BAR', "invoer + parameter"),
    ("is_drukriool", "Drukriolering", 'is_leiding AND medium in ("hwa", "dwa") AND druk_bar > DRUKLEIDING_GRENS_BAR', "invoer + parameter"),
    ("is_pe_sdr11", "Leiding van het type PE 80/100 SDR 11", 'materiaal == "PE" AND sdr == 11', "invoer"),
    ("raakt_kruin", "Tracédeel raakt het kruinvlak", "geo: snijdt kruinlaag van dezelfde kering", "geometrie"),
    ("dwars_door_kruin", "Tracédeel overbrugt de kruin", "geo: overbrugd aandeel kruinbreedte >= DWARS_AANDEEL", "geometrie + parameter"),
    ("kruist_referentielijn", "Tracédeel kruist de referentielijn", "geo: snijdt referentielijn", "geometrie"),
    ("dwars_aandeel_kernzone", "Overbrugd deel van de kernzonebreedte, haaks op de referentielijn gemeten", "geo: overbrugde breedte / kernzonebreedte (0-1)", "geometrie"),
    ("dwars_door_kernzone", "Dwars door de kernzone (2.15 lid 3): overbrugt minimaal DWARS_AANDEEL van de kernzonebreedte, gemeten waar het deel de referentielijn kruist", "dwars_aandeel_kernzone >= DWARS_AANDEEL", "geometrie + parameter"),
    ("hoek_met_kering", "Hoek tussen tracédeel en dichtstbijzijnde stuk referentielijn, 0-90 graden", "geo", "geometrie"),
    ("loodrecht", "Zoveel mogelijk loodrecht op de kering", "hoek_met_kering >= HOEK_MIN", "geometrie + parameter"),
]

VERGUNNING = [
    # id, lid, zones, voorwaarde, tekst bij vergunning
    ("V-2.15.2", "2.15.2", ["WK-KZ"],
     "NOT is_huisaansluiting AND NOT is_215_lid5 AND is_drukleiding AND is_aanleg",
     "Het is verboden zonder omgevingsvergunning een drukleiding aan te leggen, te hebben of te vernieuwen in de kernzone van een waterkerend dijklichaam."),
    ("V-2.15.3", "2.15.3", ["WK-KZ"],
     "NOT is_huisaansluiting AND NOT is_215_lid5 AND is_aanleg AND dwars_door_kernzone AND NOT gestuurde_boring",
     "Het is verboden zonder omgevingsvergunning een kabel of leiding aan te leggen of te vernieuwen dwars door de kernzone van een waterkerend dijklichaam, anders dan met een gestuurde boring."),
    ("V-2.15.4", "2.15.4", ["WK-KZ"],
     "NOT is_huisaansluiting AND is_verwijderen",
     "Het is verboden zonder omgevingsvergunning een kabel of leiding te verwijderen uit de kernzone van een waterkerend dijklichaam."),
]

REGIMES = [
    # code, artikel, voorwaarde, omschrijving
    ("R-3.18", "3.18", "is_318", "Spoedeisende reparatie, lasgat, proefsleuf of blazen"),
    ("R-3.17", "3.17", "is_verwijderen AND NOT is_318", "Verwijderen van kabels of leidingen (ook het verwijderdeel van vervangen)"),
    ("R-3.14", "3.14", "is_aanleg AND is_huisaansluiting AND NOT is_318", "Huisaansluiting"),
    ("R-3.16", "3.16", "is_aanleg AND NOT is_huisaansluiting AND gestuurde_boring AND NOT is_318", "Kabel, leiding of mantelbuis met gestuurde boring"),
    ("R-3.15K", "3.15 lid 2-5", "is_aanleg AND NOT is_huisaansluiting AND NOT gestuurde_boring AND is_kabel AND NOT is_318", "Kabel, geen huisaansluiting, geen gestuurde boring"),
    ("R-3.15L", "3.15 lid 6-7", "is_aanleg AND NOT is_huisaansluiting AND NOT gestuurde_boring AND (is_leiding OR is_mantelbuis) AND NOT is_318", "Leiding of mantelbuis, geen huisaansluiting, geen gestuurde boring"),
    ("R-ACHTER", "aanvullend", "is_achterlaten", "Leiding blijft achter in de grond; niet in de WSV, beoordeling vergunningverlener (afspraak Nico 28-10)"),
    ("R-MB", "aanvullend", "is_aanleg AND is_mantelbuis", "Aanvullende aandachtspunten mantelbuis (afspraak Nico 28-10)"),
]

# Zorgplichtregels.
# id, artikel, regime, zones, van_toepassing_als, toets, soort, tekst (WSV)
# soort: toets = getoetst, maatwerk bij niet voldoen; voorschrift = alleen opnemen; aandacht = signaal voor vergunningverlener
Z314_2 = ["WK-KZ", "WK-BZ", "HV-KZ", "HV-BZ", "VH-KZ"]
Z314_3 = ["WK-KZ", "WK-BZ", "HV-KZ"]
Z314_4 = ["WK-KZ", "WK-BZ"]
Z315_2 = ["WK-KZ", "WK-BZ", "HV-KZ", "VH-KZ"]
Z315_3 = ["WK-KZ", "WK-BZ", "HV-KZ"]
Z315_6 = ["WK-BZ", "WK-BBZ", "HV-KZ", "HV-BZ"]
Z315_7 = ["VH-KZ", "VH-BZ"]
Z316 = ["WK-KZ", "HV-KZ", "HV-BZ", "VH-KZ", "VH-BZ"]
Z316_WKHV = ["WK-KZ", "HV-KZ", "HV-BZ"]
Z317_2 = ["WK-BZ", "HV-BZ", "VH-KZ"]
Z317_3 = ["WK-BZ", "VH-KZ"]
Z318_2 = ["WK-KZ", "WK-BZ", "HV-KZ", "HV-BZ", "VH-KZ"]
KRUINZONES = ["WK-KZ", "HV-KZ", "VH-KZ"]

ZORGPLICHT = [
    # ---- 3.14 huisaansluitingen
    ("3.14.2.a", "R-3.14", Z314_2, "open_ontgraving", "ontgravingsdiepte_m <= 1.0", "toets", "de sleuf een diepte heeft van maximaal 1,00 meter;"),
    ("3.14.2.b", "R-3.14", Z314_2, "", "ontgravingsdiepte_m <= 1.0", "toets", "de huisaansluiting op maximaal 1,00 meter diepte onder het maaiveld ligt;"),
    ("3.14.2.c", "R-3.14", Z314_2, "is_leiding", "is_pe_sdr11", "toets", "de leiding van het type PE80/100 SDR11 is;"),
    ("3.14.2.d", "R-3.14", Z314_2, "", "", "voorschrift", "de leiding wordt aangelegd conform de toepasselijke NEN-normen;"),
    ("3.14.2.e", "R-3.14", Z314_2, "", "loodrecht", "toets", "de huisaansluiting zoveel mogelijk loodrecht op de kering wordt gelegd;"),
    ("3.14.2.f", "R-3.14", Z314_2, "", "", "voorschrift", "de werkzaamheden niet worden gestart en uitgevoerd wanneer het langdurig regent of vriest of wanneer dit wordt voorspeld;"),
    ("3.14.2.g", "R-3.14", Z314_2, "is_leiding", "", "voorschrift", "koppelingen ten minste dezelfde druk kunnen weerstaan als de leiding;"),
    ("3.14.2.h", "R-3.14", Z314_2, "", "", "voorschrift", "ontgravingen tot het minimum worden beperkt."),
    ("3.14.3.a", "R-3.14", Z314_3, "", "", "voorschrift", "als de huisaansluiting wordt geclusterd met andere huisaansluitingen: er voldoende ruimte is tussen de afzonderlijke leidingen om de grond goed te kunnen verdichten;"),
    ("3.14.3.b", "R-3.14", Z314_3, "is_drinkwater", "diameter_mm <= 40", "toets", "een drinkwaterleiding een uitwendige diameter heeft kleiner dan of gelijk aan 40 mm;"),
    ("3.14.3.c", "R-3.14", Z314_3, "is_gas", "diameter_mm <= 40 AND druk_bar <= 0.1", "toets", "een gasleiding een uitwendige diameter heeft kleiner dan of gelijk aan 40 mm en een druk kleiner dan of gelijk aan 10 kPa;"),
    ("3.14.3.d.1", "R-3.14", Z314_3, "is_vrijverval_riool", "diameter_mm <= 125", "toets", "een rioolleiding een uitwendige diameter heeft kleiner dan of gelijk aan 125 mm bij een vrijvervalleiding;"),
    ("3.14.3.d.2", "R-3.14", Z314_3, "is_drukriool", "diameter_mm <= 75", "toets", "een rioolleiding een uitwendige diameter heeft kleiner dan of gelijk aan 75 mm bij een drukriolering;"),
    ("3.14.3.e", "R-3.14", Z314_3, "", "", "voorschrift", "de stabiliteit en het waterkerend vermogen van de waterkering niet worden aangetast;"),
    ("3.14.3.f", "R-3.14", Z314_3, "open_ontgraving", "", "voorschrift", "direct na het aanbrengen van de huisaansluiting en aan het einde van iedere werkdag de ontgraving wordt aangevuld met de uitkomende grond in omgekeerde volgorde in lagen van maximaal 0,20 meter, waarbij elke laag afzonderlijk wordt verdicht en waarbij niet wordt verdicht met bevroren grond;"),
    ("3.14.3.g", "R-3.14", Z314_3, "raakt_kruin AND open_ontgraving", "", "voorschrift", "sleufontgravingen gefaseerd worden uitgevoerd, zodat niet de gehele kruin wordt doorgraven;"),
    ("3.14.3.h", "R-3.14", Z314_3, "", "", "voorschrift", "verwijderde of beschadigde verharding, goed aansluitend op de bestaande verharding, wordt hersteld en uitgestoken graszoden worden teruggelegd of, bij het ontbreken van geschikte graszoden, de kale plekken worden ingezaaid met graszaad."),
    ("3.14.4.a", "R-3.14", Z314_4, "", "open_ontgraving", "toets", "de huisaansluiting in een open ontgraving wordt gelegd;"),
    ("3.14.4.b", "R-3.14", Z314_4, "raakt_kruin", 'kwelscherm_kleikist == "ja"', "toets", "een huisaansluiting, die geheel of gedeeltelijk wordt aangelegd in de kruin van de waterkering, wordt voorzien van een kwelscherm met een kleikist;"),
    ("3.14.4.c", "R-3.14", Z314_4, "raakt_kruin", "", "voorschrift", "kwelschermen minimaal 0,5 meter buiten de leiding steken, waterdicht met de leiding worden verbonden en in een kleikist met een dikte van minimaal 1,00 meter in de lengterichting van de leiding worden gevat;"),
    ("3.14.4.d", "R-3.14", Z314_4, "raakt_kruin", "", "voorschrift", "het kwelscherm met kleikist in de kernzone zo dicht mogelijk bij de hoogwaterzijde wordt aangebracht;"),
    ("3.14.4.e", "R-3.14", Z314_4, "", "", "voorschrift", "de afwatering van de waterkering niet wordt belemmerd;"),
    ("3.14.4.f", "R-3.14", Z314_4, 'kruist_teensloot == "ja"', "", "voorschrift", "bij doorkruising van een teensloot een (boog)zinker in de richting van de polder wordt aangelegd vanuit het dijklichaam;"),
    ("3.14.4.g", "R-3.14", Z314_4, 'kruist_teensloot == "ja"', "", "voorschrift", "een (boog)zinker wordt ingebracht maximaal 1,00 meter vanuit de insteek van de teensloot, aan de zijde van de waterkering;"),
    ("3.14.4.h", "R-3.14", Z314_4, 'boormethode == "boogzinker"', "loodrecht", "toets", "een (boog)zinker zoveel mogelijk loodrecht op de waterkering wordt aangelegd;"),
    ("3.14.4.i", "R-3.14", Z314_4, "is_mantelbuis", "NOT dwars_door_kruin", "toets", "een mantelbuis niet dwars door de kruin wordt aangelegd."),
    ("3.14.5.a", "R-3.14", ["VH-BZ"], "", "", "voorschrift", "de leiding wordt aangelegd conform de toepasselijke NEN-normen;"),
    ("3.14.5.b", "R-3.14", ["VH-BZ"], "is_leiding", "", "voorschrift", "koppelingen ten minste dezelfde druk kunnen weerstaan als de leiding."),
    # ---- 3.15 kabels
    ("3.15.2.a", "R-3.15K", Z315_2, "open_ontgraving", "ontgravingsdiepte_m <= 1.0", "toets", "de sleuf een diepte heeft van maximaal 1,00 meter;"),
    ("3.15.2.b", "R-3.15K", Z315_2, "", "ontgravingsdiepte_m <= 1.0", "toets", "de kabel op maximaal 1,00 meter diepte onder het maaiveld ligt;"),
    ("3.15.2.c", "R-3.15K", Z315_2, "", "", "voorschrift", "ontgravingen tot het minimum worden beperkt;"),
    ("3.15.2.d", "R-3.15K", Z315_2, "", "", "voorschrift", "de verwijderde of beschadigde verharding, goed aansluitend op de bestaande verharding, wordt hersteld."),
    ("3.15.3.a", "R-3.15K", Z315_3, "open_ontgraving", 'kabelsoort != "hoogspanning"', "toets", "geen hoogspanningskabels worden aangelegd;"),
    ("3.15.3.b", "R-3.15K", Z315_3, "open_ontgraving", "", "voorschrift", "de werkzaamheden niet worden gestart en uitgevoerd wanneer het langdurig regent of vriest of wanneer dit wordt voorspeld;"),
    ("3.15.3.c", "R-3.15K", Z315_3, "open_ontgraving", "", "voorschrift", "de stabiliteit en het waterkerend vermogen van de waterkering niet wordt aangetast;"),
    ("3.15.3.d", "R-3.15K", Z315_3, "open_ontgraving", "", "voorschrift", "de afwatering van de waterkering niet door de werkzaamheden wordt belemmerd;"),
    ("3.15.3.e", "R-3.15K", Z315_3, "open_ontgraving", "", "voorschrift", "ontgravingen tot het minimum worden beperkt;"),
    ("3.15.3.f", "R-3.15K", Z315_3, "open_ontgraving", "", "voorschrift", "direct na het aanbrengen van de kabel, en, wanneer de kabel in de kernzone ligt, aan het eind van iedere werkdag, de ontgraving wordt aangevuld met de uitgekomen grond in lagen van maximaal 0,20 meter, waarbij elke laag afzonderlijk wordt verdicht en waarbij niet wordt verdicht met bevroren grond;"),
    ("3.15.3.g", "R-3.15K", Z315_3, "open_ontgraving", "", "voorschrift", "de sleuf maximaal 20 meter open ligt;"),
    ("3.15.3.h", "R-3.15K", Z315_3, "open_ontgraving", "", "voorschrift", "de verwijderde of beschadigde verharding, goed aansluitend aan de bestaande verharding, wordt hersteld, waarbij uitgestoken graszoden worden teruggelegd of, bij het ontbreken van geschikte graszoden, de kale plekken worden ingezaaid met graszaad."),
    ("3.15.4", "R-3.15K", ["WK-BZ"], "", "afstand_binnenteen_m >= 1.0", "toets", "de kabel op een afstand ligt van ten minste 1,00 meter uit de binnenteen van de dijk."),
    ("3.15.5", "R-3.15K", ["HV-KZ"], "", "", "voorschrift", "bij geclusterde kabels er voldoende ruimte blijft tussen de afzonderlijke leidingen om de grond goed te kunnen verdichten."),
    # ---- 3.15 leidingen (en mantelbuizen)
    ("3.15.6.a", "R-3.15L", Z315_6, "", "open_ontgraving", "toets", "de leiding wordt aangelegd in een open ontgraving;"),
    ("3.15.6.b", "R-3.15L", Z315_6, "is_leiding", "druk_bar <= 5", "toets", "geen leidingen met een druk van meer dan 500 kPa worden aangelegd;"),
    ("3.15.6.c", "R-3.15L", Z315_6, "is_gas", "diameter_mm <= 250", "toets", "een gasleiding een uitwendige diameter heeft van maximaal 250 mm;"),
    ("3.15.6.d", "R-3.15L", Z315_6, "is_drinkwater", "diameter_mm <= 110", "toets", "een drinkwaterleiding een uitwendige diameter heeft van maximaal 110 mm;"),
    ("3.15.6.e.1", "R-3.15L", Z315_6, "is_vrijverval_riool", "diameter_mm <= 125", "toets", "een rioolleiding een uitwendige diameter heeft kleiner dan of gelijk aan 125 mm bij een vrijvervalleiding;"),
    ("3.15.6.e.2", "R-3.15L", Z315_6, "is_drukriool", "diameter_mm <= 75", "toets", "een rioolleiding een uitwendige diameter heeft kleiner dan of gelijk aan 75 mm bij een drukriolering;"),
    ("3.15.6.f", "R-3.15L", Z315_6, "open_ontgraving", "ontgravingsdiepte_m <= 1.0", "toets", "de diepte van de sleuf maximaal 1,00 meter bedraagt;"),
    ("3.15.6.g", "R-3.15L", Z315_6, "", "", "voorschrift", "de leiding buiten de NEN-veiligheidszone ligt;"),
    ("3.15.6.h", "R-3.15L", Z315_6, "is_leiding", "is_pe_sdr11", "toets", "een leiding uit het type PE 80/100 SDR 11 bestaat;"),
    ("3.15.6.i", "R-3.15L", Z315_6, "is_leiding", "", "voorschrift", "koppelingen zodanig worden uitgevoerd dat zij dezelfde of een grotere druk dan de leiding kunnen weerstaan;"),
    ("3.15.6.j", "R-3.15L", Z315_6, "", "", "voorschrift", "de stabiliteit en het waterkerend vermogen van de waterkering niet worden aangetast;"),
    ("3.15.6.k", "R-3.15L", Z315_6, "", "", "voorschrift", "de afwatering van de waterkering niet door de werkzaamheden wordt belemmerd;"),
    ("3.15.6.l", "R-3.15L", Z315_6, "", "", "voorschrift", "ontgravingen tot het minimum worden beperkt;"),
    ("3.15.6.m", "R-3.15L", Z315_6, "open_ontgraving", "", "voorschrift", "direct na het aanbrengen van de kabel of leiding de ontgraving wordt aangevuld met de uitgekomen grond in lagen van maximaal 0,20 meter, waarbij elke laag afzonderlijk wordt verdicht en waarbij niet wordt verdicht met bevroren grond;"),
    ("3.15.6.n", "R-3.15L", Z315_6, "", "", "voorschrift", "verwijderde of beschadigde verharding, goed aansluitend aan de bestaande verharding, wordt hersteld en uitgestoken graszoden worden teruggelegd of, bij het ontbreken van geschikte graszoden, de kale plekken worden ingezaaid met graszaadmengsel."),
    ("3.15.7.a", "R-3.15L", Z315_7, "", "", "voorschrift", "de leiding wordt aangelegd conform de geldende NEN-normen;"),
    ("3.15.7.b", "R-3.15L", Z315_7, "is_leiding", "", "voorschrift", "koppelingen zodanig worden uitgevoerd dat deze dezelfde of een grotere belasting kunnen weerstaan;"),
    ("3.15.7.c", "R-3.15L", Z315_7, "", "", "voorschrift", "ontgravingen tot het minimum worden beperkt;"),
    ("3.15.7.d", "R-3.15L", Z315_7, "open_ontgraving", "", "voorschrift", "direct na het aanbrengen van de kabel of leiding de ontgraving aangevuld met de uitkomende grond in lagen van maximaal 0,20 meter, waarbij elke laag afzonderlijk wordt verdicht."),
    ("2.13-WK-KZ", "R-3.15L", ["WK-KZ"], "", "", "aandacht", "Voor een leiding in de kernzone van een waterkerend dijklichaam die niet vergunningplichtig is, noemt art. 3.15 geen specifieke regels. Alleen de algemene zorgplicht van art. 2.13 geldt; beoordeel zelf of maatwerk nodig is."),
    # ---- 3.16 gestuurde boringen
    ("3.16.a", "R-3.16", Z316, "is_drinkwater", "diameter_mm <= 110", "toets", "een drinkwaterleiding een uitwendige diameter heeft van maximaal 110 mm;"),
    ("3.16.b.1", "R-3.16", Z316, "is_vrijverval_riool", "diameter_mm <= 125", "toets", "een rioolleiding een uitwendige diameter heeft kleiner dan of gelijk aan 125 mm bij een vrijvervalleiding;"),
    ("3.16.b.2", "R-3.16", Z316, "is_drukriool", "diameter_mm <= 75", "toets", "een rioolleiding een uitwendige diameter heeft kleiner dan of gelijk aan 75 mm bij een drukriolering;"),
    ("3.16.c", "R-3.16", Z316, "", "", "voorschrift", "een gestuurde boring plaatsvindt volgens de toepasselijke NEN-normen of gelijkwaardige normen;"),
    ("3.16.d", "R-3.16", Z316, "is_leiding", "is_pe_sdr11", "toets", "een leiding uit het type PE 80/100 SDR 11 bestaat;"),
    ("3.16.e", "R-3.16", Z316, "", "", "voorschrift", "de boring wordt uitgevoerd door de 'horizontal directional drilling' (HDD) techniek of de 'gesloten front techniek' (GFT);"),
    ("3.16.f", "R-3.16", ["VH-KZ", "VH-BZ"], "", "boordiepte_onder_kruin_m >= 3", "toets", "de leiding of mantelbuis minimaal 3,00 meter onder de kruinhoogte van een verholen waterkering ligt;"),
    ("3.16.g", "R-3.16", Z316_WKHV, "", "boordiepte_onder_kruin_m >= 10 OR diepte_onder_pleistoceen_m >= 2", "toets", "de leiding of mantelbuis minimaal 10,00 meter onder de kruinhoogte ligt of minimaal 2,00 meter beneden de bovenkant van het vaste pleistocene zand, van een waterkerend dijklichaam of half-verholen waterkering;"),
    ("3.16.h", "R-3.16", Z316_WKHV, "", "", "voorschrift", "de leiding zo wordt aangelegd dat de kans op piping verwaarloosbaar is voor een waterkerend dijklichaam of een half-verholen waterkering;"),
    ("3.16.i", "R-3.16", Z316, "", "", "voorschrift", "de leiding of mantelbuis zo veel mogelijk horizontaal in de kernzone ligt;"),
    ("3.16.j", "R-3.16", Z316, "", "", "voorschrift", "het in- en uittredepunt van de boring buiten de NEN-veiligheidszone ligt;"),
    ("3.16.k", "R-3.16", Z316, "", "loodrecht", "toets", "de leiding of mantelbuis zo veel mogelijk loodrecht de kernzone kruist;"),
    ("3.16.l", "R-3.16", Z316, "", "", "voorschrift", "kruisingen van leidingen en mantelbuizen zoveel mogelijk worden geconcentreerd volgens de onderlinge veiligheidsafstand."),
    # ---- 3.17 verwijderen
    ("3.17.2.a", "R-3.17", Z317_2, "", "", "voorschrift", "ontgravingen tot het minimum worden beperkt;"),
    ("3.17.2.b", "R-3.17", Z317_2, "", "", "voorschrift", "direct na het verwijderen van de kabel of leiding, en aan het einde van iedere werkdag, de ontgraving wordt aangevuld met de uitgekomen grond in lagen van maximaal 0,20 meter, waarbij elke laag afzonderlijk wordt verdicht;"),
    ("3.17.2.c", "R-3.17", Z317_2, "", "", "voorschrift", "de holle ruimte van de verwijderde kabel of leiding wordt opgevuld met klei alvorens de uitgekomen grond in omgekeerde volgorde weer in te brengen en te verdichten; verdichten met bevroren grond is niet toegestaan."),
    ("3.17.3.a", "R-3.17", Z317_3, "", "ontgravingsdiepte_m <= 1.2", "toets", "de te verwijderen kabel of leiding op maximaal 1,20 meter diepte ligt;"),
    ("3.17.3.b", "R-3.17", Z317_3, "", "", "voorschrift", "de werkzaamheden niet worden gestart en uitgevoerd wanneer het langdurig regent of vriest of wanneer dit wordt voorspeld;"),
    ("3.17.3.c", "R-3.17", Z317_3, "", "", "voorschrift", "verwijderde of beschadigde verharding, goed aansluitend aan de bestaande verharding, wordt hersteld;"),
    ("3.17.3.d", "R-3.17", Z317_3, "", "", "voorschrift", "uitgestoken graszoden worden teruggelegd en kale plekken worden ingezaaid met graszaad."),
    ("3.17.4.a", "R-3.17", ["WK-BZ"], "", "", "voorschrift", "de stabiliteit en het waterkerend vermogen van de waterkering niet worden aangetast;"),
    ("3.17.4.b", "R-3.17", ["WK-BZ"], "", "", "voorschrift", "de afwatering van de waterkering niet wordt belemmerd;"),
    ("3.17.4.c", "R-3.17", ["WK-BZ"], "", "", "voorschrift", "de sleuf in delen van telkens maximaal 20 meter wordt gegraven nadat het voorgaande deel is aangevuld en verdicht."),
    # ---- 3.18 spoed, lasgat, proefsleuf, blazen (informerend, afspraak Nico 28-10)
    ("3.18.2.a", "R-3.18", Z318_2, 'werkwijze == "spoed_reparatie"', "", "voorschrift", "de reparatie niet ter vervanging van de kabel of leiding is;"),
    ("3.18.2.b", "R-3.18", Z318_2, "", "", "voorschrift", "de uitvoerder van de reparatie de aanwijzingen opvolgt van het bestuur;"),
    ("3.18.2.c", "R-3.18", Z318_2, "", "", "voorschrift", "ontgravingen tot het minimum worden beperkt;"),
    ("3.18.2.d", "R-3.18", Z318_2, "", "", "voorschrift", "de ontgraving direct na het gereed komen van de reparatie wordt aangevuld met de uitgekomen grond in omgekeerde volgorde en verdicht in lagen van maximaal 0,20 meter, waarbij aan het eind van elke werkdag de ontgraving volledig wordt opgevuld;"),
    ("3.18.2.e", "R-3.18", Z318_2, "", "", "voorschrift", "uitgekomen verharding of grond, goed aansluitend aan het omringende maaiveld, wordt hersteld en uitgestoken graszoden worden teruggebracht, of bij het ontbreken van geschikte graszoden worden de kale plekken ingezaaid met graszaad."),
    ("3.18.3.a", "R-3.18", ["WK-KZ"], 'werkwijze == "proefsleuf"', "", "voorschrift", "een proefsleuf maximaal 20 meter lang en maximaal 0,80 meter breed is;"),
    ("3.18.3.b", "R-3.18", ["WK-KZ"], 'werkwijze in ("lasgat", "blazen")', "", "voorschrift", "een lasgat maximaal 1,50 meter lang en maximaal 1,50 meter breed is;"),
    ("3.18.3.c", "R-3.18", ["WK-KZ"], "dwars_door_kruin", "", "voorschrift", "bij een ontgraving dwars door de kruin steeds niet meer dan 1/3 van de kruin open ligt;"),
    ("3.18.3.d", "R-3.18", ["WK-KZ"], "", "", "voorschrift", "een ontgraving tot maximaal 1,00 meter diep onder het maaiveld reikt."),
    # ---- aanvullend achterblijvende leidingen (niet in WSV, afspraak Nico 28-10)
    ("AL-1", "R-ACHTER", KRUINZONES, 'werkwijze == "achterlaten"', "", "aandacht", "Leiding blijft zonder volschuimen achter in de kernzone: risico op lekkage door de kering heen. Overweeg als voorschrift dat de leiding wordt volgeschuimd."),
    ("AL-2", "R-ACHTER", ["WK-KZ", "WK-BZ", "HV-KZ", "HV-BZ", "VH-KZ", "VH-BZ"], 'werkwijze == "volschuimen"', "", "voorschrift", "de achterblijvende leiding over de volle lengte in het beperkingengebied wordt volgeschuimd, zodat er geen water door de leiding kan lopen."),
    # ---- aanvullend mantelbuis
    ("MB-1", "R-MB", KRUINZONES, "dwars_door_kruin", "", "aandacht", "Mantelbuis haaks door de kruin van de kering: specifiek beoordelen (afspraak Nico 28-10). Wat door de mantelbuis gaat, wordt apart als kabel of leiding getoetst."),
]

# Testgevallen: één tracédeel met eigenschappen, zone en geo-feiten, plus verwacht oordeel.
# oordeel (zwaar naar licht): vergunning / maatwerk / onvolledig / aandacht / voorschriften / geen_specifieke_regels / buiten_beperkingengebied
TESTGEVALLEN = [
    ("T01", "Gasleiding 8 bar dwars door WK-kernzone, open ontgraving", "WK-KZ",
     dict(type="leiding", doel="distributie", werkwijze="nieuw", boormethode="geen", medium="gas", druk_bar=8, diameter_mm=160, materiaal="PE", sdr=11, ontgravingsdiepte_m=1.0),
     dict(kruist_referentielijn=True, dwars_aandeel_kernzone=1.0, hoek_met_kering=85, raakt_kruin=True, dwars_door_kruin=True),
     "vergunning", "2.15.2 en 2.15.3"),
    ("T02", "Glasvezelkabel dwars door WK-kernzone met gestuurde boring", "WK-KZ",
     dict(type="kabel", doel="distributie", werkwijze="nieuw", boormethode="gestuurde_boring", kabelsoort="telecom", boordiepte_onder_kruin_m=12),
     dict(kruist_referentielijn=True, dwars_aandeel_kernzone=1.0, hoek_met_kering=88, raakt_kruin=True, dwars_door_kruin=True),
     "voorschriften", "geen vergunning (boring), 3.16 voldoet"),
    ("T03", "Kabel in lengterichting in WK-kernzone, open ontgraving 0,8 m", "WK-KZ",
     dict(type="kabel", doel="distributie", werkwijze="nieuw", boormethode="geen", kabelsoort="laagspanning", ontgravingsdiepte_m=0.8),
     dict(kruist_referentielijn=False, dwars_aandeel_kernzone=0.2, hoek_met_kering=5, raakt_kruin=False, dwars_door_kruin=False),
     "voorschriften", "3.15.2 en 3.15.3 voldoen"),
    ("T04", "Kabel in WK-kernzone, 75% van de breedte overbrugd, kruist referentielijn niet", "WK-KZ",
     dict(type="kabel", doel="distributie", werkwijze="nieuw", boormethode="geen", kabelsoort="telecom", ontgravingsdiepte_m=0.8),
     dict(kruist_referentielijn=False, dwars_aandeel_kernzone=0.8, hoek_met_kering=70, raakt_kruin=False, dwars_door_kruin=False),
     "vergunning", "2.15.3 via DWARS_AANDEEL"),
    ("T05", "Kabel verwijderen uit WK-kernzone", "WK-KZ",
     dict(type="kabel", doel="distributie", werkwijze="verwijderen", boormethode="geen", kabelsoort="laagspanning", ontgravingsdiepte_m=0.7),
     dict(kruist_referentielijn=False, dwars_aandeel_kernzone=0.3, hoek_met_kering=10, raakt_kruin=False, dwars_door_kruin=False),
     "vergunning", "2.15.4"),
    ("T06", "Drinkwaterleiding Ø160 in WK-beschermingszone", "WK-BZ",
     dict(type="leiding", doel="distributie", werkwijze="nieuw", boormethode="geen", medium="drinkwater", druk_bar=4, diameter_mm=160, materiaal="PE", sdr=11, ontgravingsdiepte_m=1.0),
     dict(kruist_referentielijn=False, dwars_aandeel_kernzone=0.0, hoek_met_kering=10, raakt_kruin=False, dwars_door_kruin=False),
     "maatwerk", "3.15.6.d (diameter > 110)"),
    ("T07", "Drinkwaterleiding in WK-beschermingszone, druk onbekend", "WK-BZ",
     dict(type="leiding", doel="distributie", werkwijze="nieuw", boormethode="geen", medium="drinkwater", diameter_mm=110, materiaal="PE", sdr=11, ontgravingsdiepte_m=1.0),
     dict(kruist_referentielijn=False, dwars_aandeel_kernzone=0.0, hoek_met_kering=10, raakt_kruin=False, dwars_door_kruin=False),
     "onvolledig", "druk_bar ontbreekt (3.15.6.b) - vraag aan vergunningverlener"),
    ("T08", "Gas-huisaansluiting Ø32 100 mbar loodrecht door WK-kruin met kwelscherm", "WK-KZ",
     dict(type="leiding", doel="huisaansluiting", werkwijze="nieuw", boormethode="geen", medium="gas", druk_bar=0.1, diameter_mm=32, materiaal="PE", sdr=11, ontgravingsdiepte_m=0.9, kwelscherm_kleikist="ja", kruist_teensloot="nee"),
     dict(kruist_referentielijn=True, dwars_aandeel_kernzone=1.0, hoek_met_kering=85, raakt_kruin=True, dwars_door_kruin=True),
     "voorschriften", "huisaansluiting: 2.15 n.v.t., 3.14 voldoet"),
    ("T09", "Huisaansluiting onder hoek van 50 graden", "WK-BZ",
     dict(type="leiding", doel="huisaansluiting", werkwijze="nieuw", boormethode="geen", medium="drinkwater", druk_bar=3, diameter_mm=32, materiaal="PE", sdr=11, ontgravingsdiepte_m=0.9, kruist_teensloot="nee"),
     dict(kruist_referentielijn=False, dwars_aandeel_kernzone=0.0, hoek_met_kering=50, raakt_kruin=False, dwars_door_kruin=False),
     "maatwerk", "3.14.2.e (hoek < HOEK_MIN)"),
    ("T10", "Blazen van glasvezel in WK-kernzone", "WK-KZ",
     dict(type="kabel", doel="distributie", werkwijze="blazen", boormethode="geen", kabelsoort="telecom"),
     dict(kruist_referentielijn=True, dwars_aandeel_kernzone=1.0, hoek_met_kering=80, raakt_kruin=True, dwars_door_kruin=True),
     "voorschriften", "3.18, geen vergunning (2.15 lid 5)"),
    ("T11", "Vrijverval DWA Ø200 in HV-kernzone", "HV-KZ",
     dict(type="leiding", doel="distributie", werkwijze="nieuw", boormethode="geen", medium="dwa", druk_bar=0, diameter_mm=200, materiaal="PVC", ontgravingsdiepte_m=1.5),
     dict(kruist_referentielijn=False, dwars_aandeel_kernzone=0.4, hoek_met_kering=30, raakt_kruin=False, dwars_door_kruin=False),
     "maatwerk", "3.15.6.e.1, 3.15.6.f, 3.15.6.h"),
    ("T12", "Vrijverval riool in lengterichting WK-kernzone", "WK-KZ",
     dict(type="leiding", doel="distributie", werkwijze="nieuw", boormethode="geen", medium="hwa", druk_bar=0, diameter_mm=315, materiaal="PVC", ontgravingsdiepte_m=1.2),
     dict(kruist_referentielijn=False, dwars_aandeel_kernzone=0.2, hoek_met_kering=5, raakt_kruin=False, dwars_door_kruin=False),
     "aandacht", "geen specifieke regels, aandachtspunt 2.13"),
    ("T13", "Mantelbuis haaks door WK-kruin met gestuurde boring", "WK-KZ",
     dict(type="mantelbuis", doel="distributie", werkwijze="nieuw", boormethode="gestuurde_boring", diameter_mm=250, boordiepte_onder_kruin_m=11),
     dict(kruist_referentielijn=True, dwars_aandeel_kernzone=1.0, hoek_met_kering=89, raakt_kruin=True, dwars_door_kruin=True),
     "aandacht", "3.16 voldoet; aandachtspunt MB-1"),
    ("T14", "Kabel buiten het beperkingengebied", "",
     dict(type="kabel", doel="distributie", werkwijze="nieuw", boormethode="geen", kabelsoort="telecom", ontgravingsdiepte_m=0.6),
     dict(),
     "buiten_beperkingengebied", ""),
    ("T15", "Oude leiding blijft zonder volschuimen in WK-kernzone", "WK-KZ",
     dict(type="leiding", doel="distributie", werkwijze="achterlaten", boormethode="geen", medium="drinkwater"),
     dict(kruist_referentielijn=True, dwars_aandeel_kernzone=1.0, hoek_met_kering=85, raakt_kruin=True, dwars_door_kruin=True),
     "aandacht", "AL-1, lekkagerisico"),
    ("T16", "Oude leiding blijft in WK-kernzone en wordt volgeschuimd", "WK-KZ",
     dict(type="leiding", doel="distributie", werkwijze="volschuimen", boormethode="geen", medium="drinkwater"),
     dict(kruist_referentielijn=True, dwars_aandeel_kernzone=1.0, hoek_met_kering=85, raakt_kruin=True, dwars_door_kruin=True),
     "voorschriften", "AL-2 als voorschrift"),
]
