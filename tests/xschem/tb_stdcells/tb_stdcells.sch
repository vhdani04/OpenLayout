v {xschem version=3.4.8RC file_version=1.3}
G {}
K {}
V {}
S {}
E {}
C {asap7sc7p5t_28_R/NAND2xp33_ASAP7_75t_R/NAND2xp33_ASAP7_75t_R.sym} 0 0 0 0 {name=U1}
C {lab_pin.sym} -70.0 -10.0 0 1 {name=l1 lab=in}
C {lab_pin.sym} -70.0 10.0 0 1 {name=l2 lab=vdd}
C {lab_pin.sym} 0.0 -50.0 0 0 {name=l3 lab=vdd}
C {lab_pin.sym} 0.0 50.0 0 0 {name=l4 lab=0}
C {lab_pin.sym} 70.0 0.0 0 0 {name=l5 lab=n1}
C {asap7sc7p5t_28_R/INVx1_ASAP7_75t_R/INVx1_ASAP7_75t_R.sym} 250 0 0 0 {name=U2}
C {lab_pin.sym} 180.0 0.0 0 1 {name=l6 lab=n1}
C {lab_pin.sym} 250.0 -40.0 0 0 {name=l7 lab=vdd}
C {lab_pin.sym} 250.0 40.0 0 0 {name=l8 lab=0}
C {lab_pin.sym} 320.0 0.0 0 0 {name=l9 lab=out}
C {asap7sc7p5t_28_R/DFFHQNx1_ASAP7_75t_R/DFFHQNx1_ASAP7_75t_R.sym} 0 300 0 0 {name=U3}
C {lab_pin.sym} -70.0 290.0 0 1 {name=l10 lab=clk}
C {lab_pin.sym} -70.0 310.0 0 1 {name=l11 lab=d}
C {lab_pin.sym} 70.0 300.0 0 0 {name=l12 lab=qn}
C {lab_pin.sym} 0.0 250.0 0 0 {name=l13 lab=vdd}
C {lab_pin.sym} 0.0 350.0 0 0 {name=l14 lab=0}
C {vsource.sym} -400 0 0 0 {name=VDD value="0.7"}
C {lab_pin.sym} -400 -30 0 0 {name=l15 lab=vdd}
C {lab_pin.sym} -400 30 0 0 {name=l16 lab=0}
C {vsource.sym} -500 0 0 0 {name=VIN value="0"}
C {lab_pin.sym} -500 -30 0 0 {name=l17 lab=in}
C {lab_pin.sym} -500 30 0 0 {name=l18 lab=0}
C {vsource.sym} -400 300 0 0 {name=VD value="0.7"}
C {lab_pin.sym} -400 270 0 0 {name=l19 lab=d}
C {lab_pin.sym} -400 330 0 0 {name=l20 lab=0}
C {vsource.sym} -500 300 0 0 {name=VCLK value="pulse(0 0.7 200p 10p 10p 300p 1n)"}
C {lab_pin.sym} -500 270 0 0 {name=l21 lab=clk}
C {lab_pin.sym} -500 330 0 0 {name=l22 lab=0}
C {asap7_devices/asap7_corner/asap7_corner.sym} -500 -200 0 0 {name=CORNER1 corner=tt only_toplevel=true}
C {code_shown.sym} 300 -250 0 0 {name=s1 only_toplevel=false value=".control
dc VIN 0 0.7 10m
let lo = out[0]
let hi = out[70]
set lo_v = $&lo
set hi_v = $&hi
tran 2p 600p
meas tran qn_before find v(qn) at=150p
meas tran qn_after find v(qn) at=500p
if ($lo_v < 0.05) & ($hi_v > 0.65) & (qn_after < 0.05)
  echo PASS stdcells nand2+inv lo=$lo_v hi=$hi_v, dff qn after clk=$&qn_after
else
  echo FAIL stdcells nand2+inv lo=$lo_v hi=$hi_v, dff qn after clk=$&qn_after
end
.endc"}
