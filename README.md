# O2 TCO – OGV vs OGV+

Dette er en enkel Streamlit-app for å sammenligne total eierkost (TCO) for to alternativer:

- **OGV** (PSA): 0,90 kWh/kg O₂ (brukerforutsetning)
- **OGV+** (VPSA): 0,39 kWh/kg O₂ (brukerforutsetning)

Appen er laget for oppdrettscase med typisk behov **500–1200 kg/h per lokasjon** og kan skaleres til flåte.

## Kjør lokalt

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Hva appen gjør

- Dimensjonerer antall moduler for å møte behovet
- Beregner energibehov (kW), årlig energiforbruk (kWh)
- Sammenligner OPEX for:
  - Landstrøm (NOK/kWh)
  - Diesel via genset (dieselpris × liter/kWh)
- Beregner NPV (CAPEX + diskontert OPEX) over valgfri horisont
- Estimerer payback (diesel som default) dersom OGV+ har høyere CAPEX, men lavere OPEX

## Merk

Dette er en beslutningsstøtte, ikke et endelig tilbudsgrunnlag. Juster CAPEX/kapsiteter og forutsetninger i sidepanelet.
