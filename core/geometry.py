from panda3d.core import (
    GeomVertexFormat, GeomVertexData, GeomVertexWriter, 
    Geom, GeomTriangles, GeomNode, Texture, NodePath
)

class GeoFactory:
    @staticmethod
    def generate(key, data):
        # 1. Create the raw GeomNode
        if data.get('type') == "sprite":
            node = GeoFactory.create_billboard_sprite(key, data)
        else:
            node = GeoFactory.create_neon_grid(data)
        
        # 2. WRAP IT: Turn GeomNode into a NodePath so we can apply textures
        np = NodePath(node)
        
        # 3. APPLY TEXTURE
        if 'texture' in data:
            # We use loader.loadTexture (inherited from ShowBase/Global)
            # If this is called outside ShowBase, we use TexturePool
            from panda3d.core import TexturePool
            tex = TexturePool.loadTexture(data['texture'])
            if tex:
                tex.setMagfilter(Texture.FTNearest) 
                np.setTexture(tex)
            
        return np # Return the NodePath handle

    @staticmethod
    def create_neon_grid(data):
        vformat = GeomVertexFormat.get_v3c4t2() 
        vdata = GeomVertexData("floor", vformat, Geom.UHStatic)
        vertex, color = GeomVertexWriter(vdata, 'vertex'), GeomVertexWriter(vdata, 'color')
        tris = GeomTriangles(Geom.UHStatic)
        
        size, scale = 120, 15.0
        v_idx = 0
        for y in range(size):
            for x in range(size):
                x0, y0 = (x-60)*scale, (y-60)*scale
                vertex.addData3(x0, y0, 0); vertex.addData3(x0+scale, y0, 0)
                vertex.addData3(x0+scale, y0+scale, 0); vertex.addData3(x0, y0+scale, 0)
                
                c = data.get('color_neon', (0, 1, 0.9, 1)) if (x + y) % 2 == 0 else data.get('color_base', (0.02, 0.02, 0.1, 1))
                for _ in range(4): color.addData4(*c)
                
                tris.addVertices(v_idx, v_idx + 1, v_idx + 2)
                tris.addVertices(v_idx, v_idx + 2, v_idx + 3)
                v_idx += 4
        
        geom = Geom(vdata)
        geom.addPrimitive(tris)
        node = GeomNode("neon_floor")
        node.addGeom(geom)
        return node

    @staticmethod
    def create_billboard_sprite(key, data):
        vformat = GeomVertexFormat.get_v3c4t2()
        vdata = GeomVertexData("sprite", vformat, Geom.UHStatic)
        vertex, color = GeomVertexWriter(vdata, 'vertex'), GeomVertexWriter(vdata, 'color')
        tris = GeomTriangles(Geom.UHStatic)
        
        s = data.get('scale', 10.0) / 2
        vertex.addData3(-s, 0, 0); vertex.addData3(s, 0, 0)
        vertex.addData3(s, 0, s*2); vertex.addData3(-s, 0, s*2)
        
        for _ in range(4): color.addData4(*data['color'])
        tris.addVertices(0, 1, 2); tris.addVertices(0, 2, 3)
        
        geom = Geom(vdata)
        geom.addPrimitive(tris)
        node = GeomNode(f"sprite_{key}")
        node.addGeom(geom)
        return node