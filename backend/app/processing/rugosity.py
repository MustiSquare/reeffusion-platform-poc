import numpy as np

def surface_area_from_grid(z: np.ndarray, cell_size: float = 1.0) -> float:
    area = 0.0
    rows, cols = z.shape
    for i in range(rows - 1):
        for j in range(cols - 1):
            p00=np.array([i,j,z[i,j]],float); p10=np.array([i+1,j,z[i+1,j]],float)
            p01=np.array([i,j+1,z[i,j+1]],float); p11=np.array([i+1,j+1,z[i+1,j+1]],float)
            p00[:2]*=cell_size; p10[:2]*=cell_size; p01[:2]*=cell_size; p11[:2]*=cell_size
            area += np.linalg.norm(np.cross(p10-p00,p01-p00))/2
            area += np.linalg.norm(np.cross(p11-p10,p01-p10))/2
    return float(area)

def rugosity_from_grid(z: np.ndarray, cell_size: float = 1.0) -> dict:
    surface = surface_area_from_grid(z, cell_size)
    planar = max((z.shape[0]-1)*(z.shape[1]-1)*cell_size*cell_size, 1e-9)
    local=[]
    for i in range(0,z.shape[0]-4,4):
        for j in range(0,z.shape[1]-4,4):
            tile=z[i:i+5,j:j+5]
            local.append(surface_area_from_grid(tile, cell_size)/(4*4*cell_size*cell_size))
    return {"surface_area": surface, "planar_area": planar, "rugosity": surface/planar, "local_mean": float(np.mean(local) if local else surface/planar)}
