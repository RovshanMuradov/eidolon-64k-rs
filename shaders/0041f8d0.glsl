float Bump(vec3 point,Ray ray,Sample result){if(result.materialId.w==0.0)return texture(sTD2DInputs[0],(result.intersection.xz+point.xz)*0.1).x*0.1;return 0.0;}
