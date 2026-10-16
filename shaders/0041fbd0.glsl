vec4 FogColor(vec3 direction){return vec4(mix(vec3(0.3,0.3,0.4),vec3(0.1,0.2,0.35),pow(abs(direction.y),0.5)),.3);}
