* Smoke test: per-fin saturation current at |Vgs|=|Vds|=0.7V, TT corner.
.lib asap7.lib tt
VG g 0 0.7
VGP gp 0 -0.7
VN dn 0 0.7
VP dp 0 -0.7
NN dn g 0 0 nmos_rvt l=21n nfin=1
NP dp gp 0 0 pmos_rvt l=21n nfin=1
.control
op
let ion_n = -i(VN)*1e6
let ion_p = i(VP)*1e6
if (ion_n > 30) & (ion_n < 40) & (ion_p > 25) & (ion_p < 37)
  echo PASS Ion/fin nmos_rvt = $&ion_n uA, pmos_rvt = $&ion_p uA
else
  echo FAIL Ion/fin nmos_rvt = $&ion_n uA, pmos_rvt = $&ion_p uA
end
.endc
.end
