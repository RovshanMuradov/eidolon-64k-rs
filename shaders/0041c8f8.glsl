#define CLOUDS
#define DIR_SHADOW_SETTINGS 5,1.0,40.0
#define FAR_PLANE 180.0
#define AO_AMOUNT 0.7
#define AO_SCALE 0.2
#define RAY_STEPS 160
#define REFL_NEAR_PLANE 6.0
#define REFL_STEPS 20
#define REFL_FAR_PLANE 30.0
float fField(vec3 point,out vec4 materialId){vec3 p1=point;materialId=vec4(point,0.0);float d=fTerrain(point+vec3(1.0,0.0,16.0),materialId.x)*0.6;float d1=point.y+12.5;d1+=0.05*sin(point.x*0.1+uTime);if(d1<d){float delta=abs(d-d1);d=d1+delta*0.2;float aa=abs(sin(delta*16.0));float xx=saturate(delta*5.0);materialId.w=saturate(delta*4.0);}vec4 m;point.x+=snoise(point.z*0.05+3.4)*6.0-8.0;float tunnel;const float monoRailScale=1.;d1=fMonorail((point+vec3(12.0,9.0-monoRailScale,0.0))/monoRailScale,1.0,m,2.0,tunnel)*monoRailScale;d=max(d,-tunnel+0.15);MERGE_MAT(d,materialId,d1,m);fMainCharacter(p1,d,materialId,d1,m);return d*uFudge;}
