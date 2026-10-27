# Tool-választás MCP-alapú ágensekben – röviden

## Mi a projekt?

A projekt lényege, hogy megvizsgáljuk, hogy egy LLM-alapú ágens, ha MCP-t alakalmaz, akkor mennyire és milyen módszerekkel befolyásolható az LLM tool választási döntése. Erre vizsgálok különféle módszereket, valamint később megnézzük, hogy hogyan lehet ezek ellen védekezni

## A szimulált alkalmazás

Egy  kutató asszisztens, ami jellemzően egy kódoló ágens (pl. Claude Code, Cursor) része. A fejlesztő kérdésére a weben keres, és forrásokkal alátámasztott választ ad.

Akkor hasznos, amikor a modell saját tudása nem elég:

- a tanítási adatoknál újabb könyvtárverziók és API-változások,
- ritka vagy új hibaüzenetek,
- könyvtárválasztás és összehasonlítás,
- friss sérülékenységek, szakirodalom.

Egy fejlesztő több kereső MCP szervert is telepíthet (pl. Brave, Exa, Tavily, Firecrawl), mert ezek más-más erősségekre épülnek. Ilyenkor a modell választ közöttük.

## Mit valósítok meg a rendszerből?

Egy ágens három részből áll: a **modellből**, amely dönt, a **tool-okból** (MCP szerverek), és a **hostból**, amely összeköti őket és futtatja a ciklust.

Ebből a host első lépését valósítom meg: összerakom a kérést (system prompt, tool-lista, kérdés), elküldöm a modellnek, és rögzítem, melyik tool-t választja.

- **A tool-definíciók** a valós szerverekből lementett válaszok (kiegészítve majd a sajátommal).
- **A modell**.
- **A tool-t nem hajtom végre**, és nem folytatom a beszélgetést. A mérés az első döntésnél véget ér.

A modell szemszögéből ez a választási lépés ugyanaz, mint egy valódi hostban.