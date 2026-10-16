#define AO_SCALE 0.5
vec3 Lighting(LightData data){vec3 result=vec3(0.0);result+=PointLight(data,uMainCharacterPos+vec3(0.0,0.5,0.0),vec4(uMainBotMood*0.6,0.8),0.0,16.0);vec3 point=data.intersection;pMod2(data.intersection.xz,vec2(1.0/0.15));result+=PointLight(data,vec3 (0.0,0.5,0.0),vec4(vec3(3.0),1.0),0.0,0.0);return result;}
