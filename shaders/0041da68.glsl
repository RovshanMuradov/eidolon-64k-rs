#define CLOUDS
#define DIR_SHADOW_SETTINGS 5,1.0,40.0
#define FAR_PLANE (250.0-60.0*uTimelapse*0.6)
#define AO_AMOUNT 0.7
#define AO_SCALE 0.04
#define REFL_NEAR_PLANE 0.2
#define sky_slab vec2(20.0,33.0)//moving the clouds up
float fField(vec3 point,out vec4 materialId){materialId=vec4(point,0.0);float d=fTerrainNoWater(point,materialId.x);float d1=point.y+13.0;d1+=0.05*sin(point.x*0.1+uTime);if(d1<d){float delta=abs(d-d1);d=d1+delta*0.2;float aa=abs(sin(delta*16.0));float xx=saturate(delta*5.0);materialId.w=saturate(delta*4.0);}vec4 m;fMainCharacter(point,d,materialId,d1,m);vec4 texcoord;vec3 pBeam=point+vec3(-4,10,265);d1=fAlienBase(pBeam,0.08,texcoord);if(d1<d){d=d1;materialId=vec4(texcoord.xyz,texcoord.w+10.0);}point.x+=snoise(point.z*0.05+3.4)*6.0-6.0;d1=fRoad(point+vec3(12.0,10.5,0.0),3.0,m,2.0);MERGE_MAT(d,materialId,d1,m);pBeam.z-=30.0;pBeam.x-=16.0;pBeam.y+=200.0-uBeam;d1=fCylinder(pBeam,.4,200.0);m.w=80.0;MERGE_MAT(d,materialId,d1,m);return d;}
