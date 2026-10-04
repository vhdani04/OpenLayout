v {xschem version=3.4.8RC file_version=1.3}
G {}
K {}
V {}
S {}
F {}
E {}
N 40 -40 40 -0 {lab=Z}
N 0 -70 0 30 {lab=#net1}
N 40 -20 80 -20 {lab=Z}
N -40 -20 -0 -20 {lab=#net1}
N 40 -100 40 -70 {lab=VDD}
N 40 30 40 60 {lab=0}
C {asap7_devices/nmos_rvt/nmos_rvt.sym} 20 30 0 0 {name=M1 l=20n nfin=2 nf=1 m=1}
C {asap7_devices/pmos_rvt/pmos_rvt.sym} 20 -70 0 0 {name=M2 l=20n nfin=2 nf=1 m=1}
C {gnd.sym} 40 60 0 0 {name=l1 lab=0}
C {vdd.sym} 40 -100 0 0 {name=l2 lab=VDD}
C {ipin.sym} -40 -20 0 0 {name=p_A lab=A}
C {opin.sym} 80 -20 0 0 {name=p_Z lab=Z}
