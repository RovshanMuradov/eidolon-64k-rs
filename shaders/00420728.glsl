vec4 FogColor(vec3 direction){return vec4(mix(vec3(0.0,0.3,0.4)+0.1,vec3(0.0,0.3,0.4)-0.35,pow(abs(direction.y+0.12),0.75)),0.65);}
