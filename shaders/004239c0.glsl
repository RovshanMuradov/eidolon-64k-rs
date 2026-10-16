vec4 FogColor(vec3 direction){return vec4(mix(vec3(0.2,0.45,0.6),vec3(0.04,0.08,0.1),uMaintenanceTunnel),0.75-uMaintenanceTunnel*0.25);}
