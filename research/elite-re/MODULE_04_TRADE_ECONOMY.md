# Module 04 — Trade Economy

Why does Lave sell Furs cheap and buy Computers dear? The whole
market table per system derives from the system's economy / government
/ tech-level bytes (which you produced in Module 02) plus a per-tick
fluctuation byte. The whole galactic economy is ~200 bytes of code +
tables.

Estimated time: **1–2 evenings.**

---

## Goal

Implement:

```c
typedef struct {
    char     name[12];
    uint32_t price;     // in 0.1 credits
    uint8_t  quantity;  // tonnes / kg / grams depending on unit
    uint8_t  legal_in_government_mask;
} market_entry_t;

void generate_market(system_info_t *sys, uint8_t day_of_galactic_calendar,
                     market_entry_t out[17]);  // 17 commodities
```

**Verification:** for any 5 systems in Galaxy 1, the prices and
quantities your code produces must match the BBC emulator's market
screen exactly, for any fixed day.

---

## What you'll discover

- The 17 commodity slots are: Food, Textiles, Radioactives, Slaves,
  Liquor/Wines, Luxuries, Narcotics, Computers, Machinery, Alloys,
  Firearms, Furs, Minerals, Gold, Platinum, Gem-Stones, Alien Items
- Each commodity has a **base price**, **base quantity**, and an
  **economy multiplier** (some sign-positive, some negative, scaled
  per economy type)
- The per-system fluctuation byte adds a small +/- random kick to
  every price each tick (each docking)
- Illegal goods (Slaves, Narcotics, Firearms) are gated by the
  destination system's government bits — a high-government dock
  refuses them
- Quantity is tied symmetrically to the same byte (rich systems
  short on luxuries; poor systems long)

---

## Suggested approach

### Step 1 — find the commodity table

Search the disassembly for the commodity names ("FOOD", "TEXTILES",
etc.) — they're contiguous in the binary. The table immediately
adjacent contains base price, base quantity, and economy multiplier
per commodity.

### Step 2 — find the market-generation routine

Break on the market screen (`F8` key in game I think — confirm in
your BeebEm version). The routine that fires reads the commodity
table, multiplies by the system's economy byte, adds the fluctuation,
and writes the result to display.

### Step 3 — work out the formula

For a single commodity (Food is the simplest), find the algebra:

```
price    = base_price + (economy_index * econ_multiplier) + fluctuation_offset
quantity = base_quantity - (economy_index * econ_multiplier) + fluctuation_offset
```

(Sign conventions may vary; work them out from observed values.)

### Step 4 — handle illegal goods

The government byte gates which commodities are *available* (a
government-7 Corporate State refuses Narcotics). Find the gate table.

### Step 5 — reimplement

Extend your Module 02 code with:

```python
def generate_market(sys_info, fluctuation_seed):
    market = []
    for c in COMMODITY_TABLE:
        price = c.base_price + (sys_info.economy * c.econ_multiplier_price) + fluctuation_seed
        qty   = c.base_qty   - (sys_info.economy * c.econ_multiplier_qty) + fluctuation_seed
        if not legal_in_gov(c, sys_info.government):
            continue
        market.append((c.name, price, qty))
    return market
```

### Step 6 — verify against BBC

Five systems, market screens, every commodity, every price. Diff.

---

## Your notes

### Commodity table (transcribed)

```
Name        Base Price   Base Qty   Econ Mult Price   Econ Mult Qty
----        ----------   --------   ----------------   -------------
Food        ?            ?          ?                  ?
Textiles    ?            ?          ?                  ?
...
```

### Fluctuation byte source

(how does the fluctuation byte get computed each tick? Is it derived
from a real-time source like docking count, or is it cosmetic?)

### Illegal-goods gate

(which commodities are gated by which government bits?)

---

## Verification log

Pick 5 systems and confirm every market entry:

```
System X: Food @ 19.0 cr × 17 tonnes — match?  y/n
          Textiles @ 14.0 cr × 13 m³ — match?  y/n
          ...
```

---

## When stuck

- If your prices are systematically off by a constant, you've got
  the base-price scale wrong (Elite uses 0.1-credit units; the
  display value is `price / 10`).
- If your quantities are wrong but prices right, the qty multiplier
  and price multiplier are independent — they're not the same
  econ multiplier with sign-flipped.

---

## Onward

→ `MODULE_05_COMBAT_AI.md` — the hardest module. Pirate AI, police
AI, missile lock, the flight model. State machines and trig
approximations.
