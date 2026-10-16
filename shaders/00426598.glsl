vec4 FogColor(vec3 direction){return vec4(mix(vec3(0.3,0.5,.6)*0.2,vec3(0.15),pow(abs(direction.y),0.25)),1.0);}
