#define RAY_STEPS 200
#define REFL_STEPS 100
#define FAR_PLANE 80.0
float fField(vec3 p,out vec4 materialId){vec3 p1=p;vec4 m;float d1=fHangar(p,m);float d=p.y+0.2;materialId=vec4(p,0.0);MERGE_MAT(d,materialId,d1,m);fMainCharacter(p,d,materialId,d1,m);d1=fAlienBase(p+vec3(-40.0,0.0,170.0),0.01,m)-0.2;if(d1<d-0.4){d=d1+0.2;materialId=vec4(m.xyz,m.w+11.0);}return d;}
