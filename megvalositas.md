# Tool-választás MCP-alapú ágensekben

## Sérülékenységek

1. **Szerverhamisítás**
   Legitimnek tűnő, hasonló nevű kártékony MCP szerver vagy csomag, amelyet a felhasználó tévedésből telepít.
   _Támadó:_ közzé tud tenni egy szervert egy registryben vagy csomagkezelőben.
2. **Rug pull**
   Eleinte ártalmatlan szerver, amely egy későbbi frissítéssel megváltoztatja a tool-definícióit vagy a viselkedését.
   _Támadó:_ kontrollálja egy már telepített szerver frissítéseit.
3. **Eszközmérgezés**
   A tool leírásába rejtett utasítás, amelyet a modell megbízható információként követ, akár hívás nélkül is.
   _Támadó:_ kontrollálja egy telepített tool metaadatait.
4. **Preference manipulation**
   Utasítás nélküli, reklámszerű leírás vagy válasz, amely a támadó tool-ja vagy ajánlata felé tereli az ágenst.
   _Támadó:_ kontrollálja a saját tool-ja leírását és válaszait, nem feltétlenül rosszhiszemű.
5. **Tool shadowing / névütközés**
   A legitimmel azonos vagy hasonló nevű tool, amelyet a modell helyette hív meg.
   _Támadó:_ kontrollálja egy telepített szerver tool-neveit.
6. **Megtévesztő tool-válasz**
   Rendszerüzenetnek, hibaüzenetnek vagy a felhasználónak álcázott válasz, amely a modell következő lépését irányítja.
   _Támadó:_ kontrollálja egy tool válaszait.
7. **Rosszindulatú tool-viselkedés**
   Utasítás nélkül hamis vagy torzított adatot ad, vagy a háttérben mást is csinál (pl. továbbküldi az argumentumokat).
   _Támadó:_ kontrollálja egy tool működését.
8. **Közvetett prompt injekció**
   A tool által beolvasott külső tartalomba rejtett utasítás, amelyet a modell parancsként értelmez.
   _Támadó:_ tartalmat tud elhelyezni ott, ahonnan az ágens olvas (weboldal, dokumentum, e-mail).
9. **Szolgáltatás-megtagadás**
   Óriási bemenetek vagy végtelen tool-láncok, amelyek kimerítik az erőforrásokat és az API-keretet.
   _Támadó:_ bemenetet tud juttatni az ágenshez, vagy kontrollál egy tool-t.
10. **Izoláció megkerülése**
    A modellen át továbbított rosszindulatú bemenet (path traversal, SQL-injekció), amely kitör a szerver hatóköréből.
    _Támadó:_ befolyásolni tudja a modell által küldött argumentumokat, és a szerver nem ellenőrzi őket.
11. **Titkok a helyi tárolásban**
    Titkosítatlanul tárolt API-kulcsok és tokenek, amelyeket bármely helyi kártevő kiolvashat.
    _Támadó:_ hozzáfér a felhasználó fájljaihoz.
12. **Hitelesítési és munkamenet-hibák**
    Ellopott vagy rosszul kezelt token újrahasználata, illetve confused deputy, ahol a szerver a saját, szélesebb jogaival teljesít egy kérést.
    _Támadó:_ megszerzett egy tokent, vagy kéréseket tud küldeni a szervernek.
13. **Nem biztonságos kommunikáció**
    Titkosítatlan vagy rosszul konfigurált kapcsolat, amelyen a forgalom lehallgatható vagy módosítható.
    _Támadó:_ a kliens és a szerver közötti hálózati úton helyezkedik el.

## Besorolás és fókusz

A fenti problémák egy része általános szoftverbiztonsági probláma: hamis csomagok, rosszul védett tokenek vagy titkosítatlan forgalom. Az MCP csak egy újabb hely, ahol megjelennek. A prompt injekció az AI-ágensek általános gondja, a valóban MCP-specifikus kérdések pedig abból adódnak, hogy a modell idegen, akár menet közben megváltozó tool-leírások és -válaszok alapján dönt.

Ez utóbbiakkal foglalkozom, de a prompt injekció jellegűeket (eszközmérgezés, megtévesztő válaszok) kihagyom, mert az egy külön téma. Azokat az eseteket vizsgálom, ahol nincs rejtett utasítás: a tool csak meggyőzőbbnek mutatja magát a többinél, vagy egyszerűen rossz adatot ad vissza.

## A projekt

Azt vizsgálom, hogyan választ a modell több, ugyanarra képes tool közül, és mennyire lehet ezt a döntést pusztán a leírással a saját tool javára billenteni. Ehhez egy saját kereső tool-t teszek valódi kereső MCP szerverek mellé, és ennek a leírását változtatom. Alapfeltételezés, hogy a támadó üzemeltet egy MCP szervert, amit az 'áldozat' használ.

- **Reklámszerű megfogalmazás:** a tool nem állít magáról újat, csak eladhatóbban mutatja be magát: szakértői ajánlásra hivatkozik, jó hangulatot kelt, túloz vagy érzelmekre hat.
  _Támadó:_ csak a megfogalmazáson változtat, a modellről és a felhasználók kérdéseiről nem kell tudnia semmit.
- **Szempontok kiemelése:** a tool olyan konkrét tulajdonságokat állít magáról, amelyek egy adott kérdésnél számíthatnak, például hogy friss, rendezett találatokat ad, vagy akadémiai forrásokat is lefed.
  _Támadó:_ sejtenie kell, mire figyel a modell az egyes kérdéseknél; az állításait a modell nem tudja ellenőrizni.
- **Általános tényezők:** a leírás tartalmától függetlenül azt is mérem, mennyit számít a tool neve, a paraméterek száma és a listában elfoglalt helye.
  _Támadó:_ a nevet és a paramétereket szabadon megválaszthatja, a sorrendet viszont nem ő dönti el, hanem a host és a telepítés sorrendje.
  Összességében a támadó egy átlagos MCP szerver-fejlesztő: a saját tool-ja definíciója teljesen az ő kezében van, de a többi tool-hoz, a system prompthoz, a felhasználó kérdéséhez és a hosthoz nem fér hozzá. A tool-ja közben rendesen működik, valóban keres.

A leírásban nincs utasítás, és a modell nem tér el attól, amit a felhasználó kért, ugyanúgy keres, csak a támadó keresőjét választja. A szöveg pont olyan, mint amilyet a valódi tool-ok is írnak magukról.

## Szempontok kiemelése

A tool leírását a host a munkamenet elején kéri le, és minden kérdésnél ugyanazt küldi a modellnek. A támadó tehát nem az éppen feltett kérdéshez igazítja a leírást, hanem előre céloz egy kérdéstípusra, vagy egyszerre többre.

- **Frissesség** (friss információ): folyamatosan frissülő index, modell korlátjaira hivatkozás (tanítóadat)
- **Fejlesztői források** (hibaüzenetek): GitHub issue-k, Stack Overflow, stb.
- **Összehasonlító adatok** (könyvtárválasztás): népszerűség, karbantartottság, alternatívák.
- **Akadémiai források** (szakirodalom): arXiv, Semantic Scholar.
- Illetve ezek kombinációja

## Mi a projekt?

A projekt lényege, hogy megvizsgáljam, hogy egy LLM-alapú ágens, ha MCP-t alkalmaz, akkor mennyire és milyen módszerekkel befolyásolható az LLM tool választási döntése (prompt injection nélkül). Erre vizsgálok különféle módszereket, valamint később megnézem, hogy hogyan lehet ezek ellen védekezni.

## A szimulált alkalmazás

Egy kutató asszisztens, ami jellemzően egy kódoló ágens (pl. Claude Code, Cursor) része. A fejlesztő kérdésére a weben keres, és forrásokkal alátámasztott választ ad.

Akkor hasznos, amikor a modell saját tudása nem elég:

- a tanítási adatoknál újabb könyvtárverziók és API-változások,
- ritka vagy új hibaüzenetek,
- könyvtárválasztás és összehasonlítás,
- friss sérülékenységek, szakirodalom.

Egy fejlesztő több kereső MCP szervert is telepíthet, mert ezek más-más erősségekre épülnek. Ilyenkor a modell választ közöttük.

A jelenleg használt valós MCP kereső szerverek: Brave, Tavily, Exa, Firecrawl. Ezek mellé egy saját MCP szerver definíciót készítek, és a tool-leírás megfogalmazásával próbálom rávenni az LLM-et, hogy az enyémet válassza.

## A rendszer

Az ágens három részből áll: a modellből, amely dönt, a tool-okból (MCP szerverek), és a hostból, amely összeköti őket és futtatja a ciklust.

Ebből a host első lépését valósítom meg: összerakom a kérést (system prompt, tool-lista, kérdés), elküldöm a modellnek, és rögzítem, melyik tool-t választja.

- **A tool-definíciók** a valós szerverekből lementett tool-listák (kiegészítve majd a sajátommal).
- **A modell**.
- **A tool-t nem hajtom végre**, és nem folytatom a beszélgetést. A mérés az első döntésnél véget ér.

A modell szemszögéből ez a választási lépés ugyanolyan, mint egy valódi hostban, ugyanazon az API-n, ugyanolyan szerkezetű tool-listát kap. A lementett tool-lista nem tér el a futó szerverétől, mert a modellhez úgyis csak a név, a leírás és a paraméterek jutnak el.

Az első döntés azért elég, mert a támadónak ez a lényeg. Ha nem az ő tool-ját választják, a további lépések nem számítanak, ha pedig igen, onnantól ő adja a találatokat.

## A mérés menete

**Egy mérés** egyetlen modellhívás: rögzített system prompt, egy fejlesztői kérdés és a tool-lista. Azt rögzítem, melyik tool-t hívja meg először a modell, vagy hogy egyiket sem. A modell a Gemini 3.6 Flash, alapértelmezett beállításokkal.

**A tool-lista** a négy valós kereső fő tool-jából és a saját tool-omból áll.

**A kérdések:** 32 fejlesztői kérdés, négy típusban, típusonként 8: friss információ, hibaüzenet, könyvtárválasztás, szakirodalom.

**A feltételek** a saját tool leírásváltozatai. Mindegyik ugyanabból a sablonból készül így a hosszuk és a szerkezetük azonos. Ezeket egy semleges alapváltozathoz (baseline) hasonlítom.

**A sorrend:** a modell a lista elején álló tool-okat gyakrabban választja, ezért a sorrendet kiegyensúlyozom. Kérdésenként véletlen alapsorrendet használok, és a tool-okat ennek több eltolásában adom át, így a saját tool minden pozícióba kerül. A véletlen sorrendet rögzített seed adja, ezért a mérés reprodukálható. Ugyanannál a kérdésnél minden feltétel ugyanazt a sorrendet kapja, így két feltétel mérései párban összevethetők: csak a leírásban különböznek.

**Két kar:**

- **Márkás:** a versenytársak valódi nevükkel szerepelnek, a saját tool egy fiktív névvel.
- **Anonimizált:** minden tool neve `web_search`, a szerverek kérdésenként váltakozó semleges álnevet kapnak, és a versenytársak leírásaiból kicserélem a márkára utaló részeket.

A kettő összevetése választja szét a név és a leírás hatását.

**Kiértékelés:** a saját tool választási aránya feltételenként, a baseline-hoz párosítva (ugyanaz a kérdés és sorrend).