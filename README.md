# QGIS Template (06-01-26 – QGIS Versie 3.40.14)
Deze repository bestaat uit twee delen: een template QGIS bestand met zoveel mogelijk openbaar publieke data, en een modelontwerp binnen QGIS om deze data zo makkelijk mogelijk te verwerken voor AnyLogic import. Deze ReadMe zal een korte rondleiding geven en uitleggen hoe het modelontwerp te gebruiken is.
## Wat te verwachten
Deze repository bevat de volgende dingen:
* Een verzameling van de essentiële publieke data: panden, adressen en buurten
* Vrijwel alle beschikbare kabel- en trafodata van Enexis, Stedin en Liander
* Extra data ter aanvulling, zoals het jaarverbruik van kleinverbruikers op postcode-6 niveau, energielabels, en de beheergebieden van Enexis, Stedin en Liander

Deze repository heeft (nog) niet de volgende dingen:
* Kabeldata voor Stedin. De praktische reden hiervoor is dat deze niet via een API aangeboden wordt en dat het bestand te groot is om in deze repository toe te voegen. Je kunt deze zelf [hier](https://www.stedin.net/zakelijk/open-data/liggingsdata-kabels-en-leidingen) downloaden en importeren. Kabeldata voor Stedin-Zeeland is wel inbegrepen.
* Kabel- en trafodata voor de kleinere providers buiten de bedieningsgebieden van Enexis, Stedin en Liander. Zodra we zelf hiermee te maken krijgen, zullen ze worden toegevoegd.
* Detailinformatie per trafo. Hoewel we wel weten waar de trafo’s staan, weten we niet precies welke panden hierop aangesloten staan of wat voor capaciteit ze hebben.
* Algemene zonnedata. Hoewel deze data wel openbaar beschikbaar zou moeten zijn (zie zonnedakje), is hier nog geen API of andere bron bij ons voor bekend.
* Aanvullende gebiedspecifieke data, zoals verbruiksprofielen van trafo’s, zonnepanelen per pand, parkeervakken en laadpalen. Deze zullen zelf opgevraagd moeten worden bij de gemeente of andere verantwoordelijken.
* Jaarverbruik van grootverbruikers. Dit is vertrouwelijke data die zelf bij de gebruikers opgevraagd zal moeten worden.

## Het model openen
Het model kan in QGIS geopend worden via de Modelontwerper. Deze is te vinden in het hoofdmenu onder “Processing” en daarna “Modelontwerper”, of met de sneltoets Ctrl+Alt+G op Windows.

![Toolbar](/Media/Modelontwerper-toolbar.png "Toolbar")

In een nieuw venster verschijnt nu de modelontwerper interface. Door op het mapje te klikken of met de sneltoets Ctrl+O kan het model nu geopend worden. Er zijn twee verschillende modellen: een buurtmodel en een bedrijvenmodel. Het buurtmodel is gericht op woonwijken, het bedrijvenmodel op industrieterreinen. Deze Readme zal zich focussen op het buurtmodel, omdat dit een uitgebreidere versie is dan het bedrijvenmodel.

Zodra het gewenste model geopend is, verschijnt de diagramweergave van het model. Deze bestaat uit blokken die met elkaar verbonden zijn. Ieder blok staat voor een aparte stap in het algoritme, waarvan de output van het ene gebruikt wordt als input voor het andere. Ik zal niet iedere stap individueel uitleggen, maar in grote lijnen volgt het de volgende structuur:

![Model layout](/Media/Auto-model-image.png "Model layout")

1. Input: De input die het model vereist. Dit betreft de volgende lagen: buurten, panden, adressen (verblijfsobjecten), postcode, jaarverbruik kleinverbruikers (hoeft niet in het bedrijvenmodel), trafo’s, LS- en MS-kabels. Bij ieder inputblok staat een grijs commentaarblok over welke laag het betreft of verdere specificaties.
2. Panden en adressen: Panden en adressen worden zodanig bewerkt dat ze aan elkaar gekoppeld worden en verder bewerkt zodat we de data eruit krijgen die we willen hebben voor AnyLogic.
3. Buurt en anti-laag: Op basis van de geselecteerde buurt wordt een anti-laag gemaakt, die samen worden geëxporteerd.
4. Trafo’s: Betreft voornamelijk de locaties van trafostations met wat algemene aanvullende informatie, afhankelijk van de netbeheerder. De laag die hiervoor gebruikt wordt verschilt per netbeheerder.
5. Net neighbours: Op basis van een nearest-neighbour algoritme wordt een ruwe indeling gemaakt van panden per trafo. Deze stap wordt niet gedaan in het bedrijvenmodel, aangezien dit daar niet nodig is.
6. Kabels (optioneel): Kabelsegmenten doen we op basis van een gemeenschappelijk label groeperen en exporteren. We kunnen op dit moment nog niet kabels aan specifieke trafo’s koppelen, hoewel we dit wel graag in de toekomst nog zouden willen doen.
7. Output: Voor punten 2 t/m 6 wordt er ieder een excel-bestand gegenereerd wat vrijwel direct in AnyLogic ingeladen kan worden.

Omdat sommige invoer afhankelijk is van welke data je gebruikt, kan het zijn dat er bepaalde code verbonden en geactiveerd of gedeactiveerd moet worden. **Zorg ervoor dat de te deactiveren code niet meer als invoer wordt gebruikt voor code die je wel wilt behouden.** Een stuk code wat gedeactiveerd wordt zal namelijk alles wat erna komt ook deactiveren. Op dezelfde manier zal een stuk te activeren code stapsgewijs van voren naar achteren geactiveerd moeten worden.

Je kunt ook handmatig stappen in het algoritme overslaan of in een andere volgorde doen. Hiervoor moet je een stap bewerken door er op rechts te klikken en de invoer wijzigen naar de gewenste vorige stap. Dit kan handig zijn als je een bepaalde stap toch liever niet wilt, zoals panden limiteren tot de geselecteerde buurt in het geval je zelf al een selectie panden hebt. 

## Het model uitvoeren
Druk op de groene pijl of gebruik de sneltoets F5 op Windows om op het configuratiescherm voor het model te komen.

![Configuratie input](/Media/Modelontwerper-configuratie-input.png "Configuratie input")

Alle input wordt bovenaan in de vorm van dropdown-menu’s weergeven. Hiervoor worden lagen vanuit QGIS als input meegegeven. In principe zouden alle lagen zodanig genoemd moeten zijn dat logischerwijs te vinden is welke laag waar als input gebruikt moet worden. Mocht er toch nog onduidelijkheid over zijn, kijk dan naar het grijze commentaarvak bij de invoer op de diagramweergave.

Als er [optioneel] achter een invoerveld staat, kan deze leeggelaten worden. Zorg er dan wel voor dat alle code die afhankelijk is van deze invoer gedeactiveerd is, anders zal dit alsnog een error opleveren.

Voor Buurt-selected en Panden-selected is er de optie om “Alleen geselecteerde objecten” aan te vinken. Voor Buurt-selected is dit vrijwel verplicht, omdat anders de hele buurtenlaag voor heel Nederland als invoer gebruikt zal worden, wat niet alleen heel lang zal duren (als het überhaupt wilt runnen), maar ook niet heel nuttige uitvoer op zal leveren. Voor Panden-selected hoeft “Alleen geselecteerde objecten” alleen maar aangevinkt te worden als je een specifieke groep panden hebt waar je een uitdraai voor wilt maken. Deze volgen nog wel de normale stappen in het algoritme en zullen dus binnen de geselecteerde buurt(en) moeten liggen.

![Configuratie output](/Media/Modelontwerper-configuratie-output.png "Configuratie output")

Als je het model alleen maar wilt uitvoeren voor de export, moet er alleen voor de variabelen Buildings_, Neighbourhoods_, GridNodes_ NetNeighbours_ en Cables_ een bestandsnaam en -locatie gekozen worden. Als je na uitvoering nog met het QGIS-bestand verder aan de slag wilt, kan het handig zijn om de tijdelijke lagen ook alvast op te slaan, hoewel dit ook nog kan nadat het model klaar is met uitvoeren.

Als alles naar wens is, kan je op de knop “Uitvoeren” klikken om het model te starten. De eerste keer kan dit enkele minuten duren.

## Output
De output van het model bestaat uit twee delen: de geëxporteerde Excel-bestanden en de (tijdelijke) QGIS-lagen.

De Excel-bestanden zijn zodanig geformatteerd dat ze met minimale wijzigingen direct geïmporteerd kunnen worden in AnyLogic. Het enige wat (helaas) nog wel handmatig gedaan zal moeten worden is het hernoemen van het tabblad in Excel naar de lowercase-benoeming van het bestand (Dus voor “Buildings_” moet dit “buildings” worden). De output-variabelen in het configuratiescherm hebben de namen die AnyLogic verwacht, dus zolang deze aangehouden worden zou dit geen problemen op moeten leveren. Kijk voor de zekerheid alle Excel-bestanden nog even na of er belangrijke kolommen leeggelaten zijn of dubbele informatie bevatten.

![GIS-weergave](/Media/Modelontwerper-map.png "GIS-weergave")

De QGIS-lagen worden na uitvoering automatisch op de map getekend. Hierboven is een voorbeeld te zien van de lagen na uitvoering van het model met Tuinzigt als geselecteerde buurt. De lagen zullen in een aparte groep geplaatst worden en zullen zodanig gesorteerd zijn dat alles zichtbaar is. Mocht het toch iets te onoverzichtelijk zijn, dan kunnen de vinkjes ernaast gebruikt worden om lagen onzichtbaar te maken. Ook kunnen de kleuren niet altijd even duidelijk zijn, aangezien deze willekeurig gekozen worden. Deze kunnen aangepast worden door op een laag rechts te klikken en “Stijlen” te selecteren. Om een tijdelijke laag permanent te maken (aangeduid met een rechthoek met streepjes rechts naast de naam), kun je op een laag rechtsklikken en vervolgens “Permanent maken” selecteren om hem lokaal op te slaan.

Wijzingen die na uitvoering van het model aangebracht worden, zoals het plaatsen van laadpalen, extra kolommen of iets anders, zullen handmatig geëxporteerd moeten worden. Hiervoor zul je de Attributentabel (sneltoets F6 op Windows) moeten gebruiken of door te rechtsklikken op de gewenste laag en “Exporteren” te selecteren. Hiervoor kun je zelf het gewenste format kiezen.

Als je het gehele QGIS-project wilt opslaan om dit later nog een keer te kunnen gebruiken, selecteer dan “Opslaan als” of gebruik de sneltoetscombinatie Ctrl+Shift+S op Windows.
