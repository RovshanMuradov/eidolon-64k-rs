#ifndef AO_SCALE
#define AO_SCALE 0.5
#endif
#ifndef AO_AMOUNT
#define AO_AMOUNT 1.0
#endif
#ifndef RAY_STEPS
#define RAY_STEPS 200
#endif
#ifndef NEAR_PLANE
#define NEAR_PLANE 0.1
#endif
#ifndef FAR_PLANE
#define FAR_PLANE 40.0
#endif
#ifndef REFL_STEPS
#define REFL_STEPS 60
#endif
#ifndef REFL_NEAR_PLANE
#define REFL_NEAR_PLANE 2.0
#endif
#ifndef REFL_FAR_PLANE
#define REFL_FAR_PLANE 40.0
#endif
vec4 Shade(Ray ray,Sample sampl,Material material){vec3 color;float a=1.0;if(sampl.emissiveColor !=vec4(0.0)){color=sampl.emissiveColor.xyz/sampl.emissiveColor.w;a=0.0;}else{color=Lighting(LightData(ray.direction,sampl.intersection,sampl.normal,material));float ao=(fField(sampl.intersection+sampl.normal*AO_SCALE)/AO_SCALE+2.0*fField(sampl.intersection+sampl.normal*AO_SCALE*0.6)/0.6/AO_SCALE+3.0*fField(sampl.intersection+sampl.normal*AO_SCALE*0.3)/0.3/AO_SCALE+4.0*fField(sampl.intersection+sampl.normal*AO_SCALE*0.1)/0.1/AO_SCALE)*0.1;color*=mix(1.0,clamp(ao,0.0,1.0),AO_AMOUNT);}color+=material.additive;return vec4(color,a);}void Normal(Ray ray,inout Sample result){vec2 eps=vec2(EPSILON*2.0,0.0);float x=fFieldAndEmissive(result.intersection+eps.xyy);float y=fFieldAndEmissive(result.intersection+eps.yxy);float z=fFieldAndEmissive(result.intersection+eps.yyx);float w=fFieldAndEmissive(result.intersection);result.normal=normalize(vec3(x,y,z)-w);x+=Bump(eps.xyy,ray,result);y+=Bump(eps.yxy,ray,result);z+=Bump(eps.yyx,ray,result);w+=Bump(vec3(0.0),ray,result);result.normal=normalize(vec3(x,y,z)-w);}Ray GetRay(){vec2 uv=(gl_FragCoord.xy*2.0-uTimeResolution.yz)/uTimeResolution.z;uv*=1.0-(1.0-dot(uv,uv)*0.25)*uFisheye;vec3 direction=vec3(0.0,0.0,1.0);pR(direction.xz,uv.x*uFovBias);pR(direction.yz,uv.y*uFovBias);pR(direction.xy,uAngles.z);pR(direction.yz,uAngles.x);pR(direction.xz,uAngles.y);return Ray(uOrigin,direction);}Sample Trace(Ray ray,int iterations,float near,float far){Sample result;result.distance=near;for(int i=0;i<iterations;++i){result.intersection=ray.origin+ray.direction*result.distance;float sampl=fFieldAndEmissive(result.intersection,result.materialId,result.emissiveColor);result.distance+=sampl;if(abs(sampl)<EPSILON || result.distance>far)break;}result.fog=clamp(result.distance/far,0.0,1.0);Normal(ray,result);return result;}vec3 DebugGradient(float x){float t=clamp(x,0.0,1.0);return clamp(vec3(sqrt(t),t*t*t,max(sin(PI*1.75*t),pow(t,12.0))),0.0,1.0);}vec3 Debug(Ray ray,float debugZ){float dist=fFieldAndEmissive(ray.origin+ray.direction*debugZ);float idealGridDistance=20.0/debugZ*pow(abs(ray.direction.y),0.8);float nearestBase=floor(log(idealGridDistance)/log(10.));float relativeDist=abs(dist/ray.origin.y);float largerDistance=pow(10.0,nearestBase+1.);float smallerDistance=pow(10.0,nearestBase);vec3 col=DebugGradient(log(1.+relativeDist));col=max(vec3(0.),col);if (sign(dist)<0.){col=col.grb*3.;}float l0=(pow(0.5+0.5*cos(dist*PI*2.*smallerDistance),10.0));float l1=(pow(0.5+0.5*cos(dist*PI*2.*largerDistance),10.0));float x=fract(log(idealGridDistance)/log(10.));l0=mix(l0,0.,smoothstep(0.5,1.0,x));l1=mix(0.,l1,smoothstep(0.0,0.5,x));col.rgb*=0.1+0.9*(1.-l0)*(1.-l1);return col;}
#ifndef CLOUD_ANIM
#define CLOUD_ANIM (uTime*0.002)
#endif
float SampleClouds(vec3 p){const float density=0.2;vec4 s=texture(uClouds,p*vec3(0.01,0.02,0.01)+CLOUD_ANIM);float a=smoothstep(0.6,0.7,s.x+(s.y-0.5)*0.25+(s.z-0.5)*0.07)*density;return a;}void main(){Ray ray=GetRay();Sample primary=Trace(ray,RAY_STEPS,NEAR_PLANE,FAR_PLANE);Material material=GetMaterial(ray,primary);
#ifdef DEBUG
float debugHeight=uDebugPlaneHeight-ray.origin.y;float debugZ=debugHeight/ray.direction.y;if(sign(ray.direction.y)==sign(debugHeight) && debugZ<primary.distance){vec4 fog=FogColor(ray.direction);outColor0=vec4(mix(Debug(ray,debugZ),fog.xyz,pow(min(1.0,debugZ/FAR_PLANE),fog.w)),1.0);outColor2=vec4(primary.distance);return;}
#endif
#ifdef CLOUDS
#ifndef CLOUD_COLORS
#define CLOUD_COLORS vec3(1.06,1.02,1.0),vec3(0.1,0.3,0.5)
#endif
#ifndef sky_slab
#define sky_slab vec2(7.0,20.0)
#endif
vec2 slab_dist=sky_slab-ray.origin.y;float sky_dist=0.0;if(sign(slab_dist).x==sign(slab_dist.y)){slab_dist/=ray.direction.y;sky_dist=min(slab_dist.x,slab_dist.y);}float cloudAlpha=0.0;vec3 cloudColor=vec3(0.0);if(sky_dist>=0.0 && sky_dist<primary.distance){vec3 isect=ray.origin+ray.direction*sky_dist;float shadow=0.0;for(int i=0;i<40;++i){float s=SampleClouds(isect);float a=cloudAlpha*cloudAlpha;s*=(1.0-sqr(a));a=saturate(sky_dist/FAR_PLANE);a*=a;s*=1.0-a*a;s*=1.0-saturate(abs( (isect.y-sky_slab.x)/(sky_slab.y-sky_slab.x)*2.0-1.0 )*6.0-5.0);float offset=8.0-(7.0*s);float occlusion=0.0;for(int j=1;j<4;++j){vec3 p=isect-(1*sun_dir*j)*((sky_slab.y-sky_slab.x)/8.0);float os=SampleClouds(p);os*=1.0-sqr(occlusion);os*=1.0-saturate(abs( (p.y-sky_slab.x)/(sky_slab.y-sky_slab.x)*2.0-1.0 )*8.0-7.0);occlusion+=os;}shadow+=occlusion*s;if(cloudAlpha+s>1.0){cloudAlpha=1.0;break;}cloudAlpha+=s;float stp=offset*((sky_slab.y-sky_slab.x)/64.0);isect+=ray.direction*stp;sky_dist+=stp;if(isect.y>sky_slab.y || isect.y<sky_slab.x || sky_dist>primary.distance)break;}cloudColor=mix(CLOUD_COLORS,shadow);cloudAlpha=smoothstep(0.5,0.9,sqrt(cloudAlpha));}
#endif
vec4 fogColor=FogColor(ray.direction);float pf=primary.fog;primary.fog=pow(primary.fog,fogColor.w);outColor0=Shade(ray,primary,material);outColor0.xyz=mix(outColor0.xyz,fogColor.xyz,pow(primary.fog,1+max(0,vmax(outColor0.xyz-1))));
#ifdef CLOUDS
outColor0.xyz=mix(outColor0.xyz,cloudColor,cloudAlpha);
#endif
outColor0.a*=material.reflectivity*(1.0-primary.fog)
#ifdef CLOUDS
*(1.0-cloudAlpha)
#endif
;if(outColor0.a==0.0){outColor1=vec4(0.0);outColor2=vec4(primary.distance);return;}Ray reflRay=Ray(primary.intersection,reflect(ray.direction,primary.normal));Sample secondary=Trace(reflRay,REFL_STEPS,REFL_NEAR_PLANE,REFL_FAR_PLANE);Material reflMaterial=GetMaterial(reflRay,secondary);fogColor=FogColor(reflRay.direction);secondary.fog=pow(min(1.0,secondary.fog+pf),fogColor.w);outColor1=Shade(reflRay,secondary,reflMaterial);outColor1.xyz=mix(outColor1.xyz,fogColor.xyz,pow(secondary.fog,1+max(0,vmax(outColor0.xyz-1))));outColor1.xyz*=mix(vec3(1.0),material.albedo,material.metallicity);outColor1.a=(material.roughness*16.0)/(1.0+primary.distance);outColor2=vec4(primary.distance);}
