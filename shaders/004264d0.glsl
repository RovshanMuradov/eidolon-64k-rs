vec3 Lighting(LightData data){vec3 result=vec3(0.0);result+=PointLight(data,vec3 (0.0,8.5,0.0),vec4(1.0,1.0,1.5,.4),.8,64.);result+=AmbientLight(data,vec3(0.162,0.177,0.2)*0.0);return result;}
