#version 450
uniform sampler2D sTD2DInputs[6];uniform sampler3D uClouds;
#ifdef DEBUG
uniform float uDebugPlaneHeight=1.0;
#endif
uniform vec3 uTimeResolution;uniform float uFovBias=0.3;uniform vec3 uOrigin=vec3(0.0,1.0,-10.0);uniform vec3 uAngles=vec3(0.0,0.0,0.0);uniform float uFisheye=0.025;
#define BPM 80.0
#define uTime uTimeResolution.x
#define uBeat (uTimeResolution.x*BPM/60.0)
#define uResolution uTimeResolution.yz
const float EPSILON=0.002;out vec4 outColor0;out vec4 outColor1;out vec4 outColor2;struct Ray{vec3 origin;vec3 direction;};struct Sample{vec3 intersection;vec3 normal;float distance;float fog;vec4 materialId;vec4 emissiveColor;};struct Material{vec3 albedo;float reflectivity;float roughness;float metallicity;vec3 additive;};struct LightData{vec3 direction;vec3 intersection;vec3 normal;Material material;};
