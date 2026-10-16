vec3 Lighting(LightData data){vec3 result=vec3(0.0);result+=RimLight(data,vec3(1.0,1.0,1.0)*0.25,2.0);result+=RimLight(data,vec3(1.0,1.0,1.0),8.0);result*=0.2+data.material.albedo;return result;}
