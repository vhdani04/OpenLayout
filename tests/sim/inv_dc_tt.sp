* Smoke test: ASAP7 RVT inverter (nfin=3) DC transfer, TT corner. Expects VM near VDD/2.
.lib asap7.lib tt
VDD vdd 0 0.7
VIN in 0 0
NP out in vdd vdd pmos_rvt l=20n nfin=3
NN out in 0 0 nmos_rvt l=20n nfin=3
.control
dc VIN 0 0.7 1m
meas dc vm when v(out)=v(in)
if (vm > 0.30) & (vm < 0.40)
  echo PASS inverter VM = $&vm V
else
  echo FAIL inverter VM = $&vm V, expected 0.30..0.40
end
.endc
.end
