v {xschem version=3.4.8RC file_version=1.3}
G {}
K {}
V {}
S {}
E {}
C {asap7_devices/pmos_rvt/pmos_rvt.sym} 0 0 0 0 {name=M1 l=20n nfin=3 nf=1 m=1}
C {asap7_devices/nmos_rvt/nmos_rvt.sym} 0 100 0 0 {name=M2 l=20n nfin=3 nf=1 m=1}
C {lab_pin.sym} 20 -30 0 0 {name=l1 lab=vdd}
C {lab_pin.sym} 20 0 0 0 {name=l2 lab=vdd}
C {lab_pin.sym} -20 0 0 1 {name=l3 lab=in}
C {lab_pin.sym} 20 30 0 0 {name=l4 lab=out}
C {lab_pin.sym} 20 70 0 0 {name=l5 lab=out}
C {lab_pin.sym} -20 100 0 1 {name=l6 lab=in}
C {lab_pin.sym} 20 100 0 0 {name=l7 lab=0}
C {lab_pin.sym} 20 130 0 0 {name=l8 lab=0}
C {vsource.sym} -200 0 0 0 {name=VDD value=0.7}
C {lab_pin.sym} -200 -30 0 0 {name=l9 lab=vdd}
C {lab_pin.sym} -200 30 0 0 {name=l10 lab=0}
C {vsource.sym} -300 0 0 0 {name=VIN value=0}
C {lab_pin.sym} -300 -30 0 0 {name=l11 lab=in}
C {lab_pin.sym} -300 30 0 0 {name=l12 lab=0}
C {asap7_devices/asap7_corner/asap7_corner.sym} -300 -150 0 0 {name=CORNER1 corner=tt only_toplevel=true}
C {code_shown.sym} 150 -150 0 0 {name=s1 only_toplevel=false value=".control
dc VIN 0 0.7 1m
meas dc vm when v(out)=v(in)
if (vm > 0.30) & (vm < 0.40)
  echo PASS xschem inverter VM = $&vm V
else
  echo FAIL xschem inverter VM = $&vm V
end
.endc"}
