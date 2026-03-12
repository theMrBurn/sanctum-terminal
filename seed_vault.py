from engine import SanctumTerminal

st = SanctumTerminal()
st.log_event(10000.00, "INITIAL_STABILITY", "Aegis Shield Locked")
st.log_event(5350.00, "RESOURCE_CACHE", "Skyloft Progress Inked")
st.log_event(350.00, "WASTELAND_SALVAGE", "Vegas Break-Even Surplus")
print("Seed Complete: ,700 Inked to Vault.")
