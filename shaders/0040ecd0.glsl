vec4 Shade(vec2 uv){vec2 s0=ManhattanVoronoi(uv);vec3 color;return vec4(s0.x,hash11(s0.y),Greeble4(uv,color),0.0);}
