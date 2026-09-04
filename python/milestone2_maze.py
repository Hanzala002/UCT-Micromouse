# =========================================================================
# UCT Micromouse - Milestone 2: Map and Navigate a Maze (Framework)
# =========================================================================
# ASSIGNMENT DESCRIPTION:
# Implement a maze explorer that maps a 10x10 grid using Time-of-Flight (ToF)
# sensors, updates its internal map, uses BFS (or another algorithm) to
# explore 100% of reachable cells, and then navigates from the finish to the
# center (cells [4,4], [4,5], [5,4], [5,5]).
# =========================================================================

import uct_mouse
import math
import time

# Constants
MAZE_DIM = 10
CELL_LENGTH_M = 0.20
TICK_DIST_M = (2.0 * math.pi * 0.031) / 8.0

# Directions: 0: North, 1: East, 2: South, 3: West
DX = [0, 1, 0, -1]
DY = [1, 0, -1, 0]

class MazeSolver:
    def __init__(self):
        # 0 = unknown, 1 = wall, 2 = open
        self.walls = [[ [0]*4 for _ in range(MAZE_DIM)] for _ in range(MAZE_DIM)]
        self.visited = [[False]*MAZE_DIM for _ in range(MAZE_DIM)]
        self.x = 0
        self.y = 0
        self.dir = 1  # Start direction (e.g. 1 = East)
        self.heading_deg = 0.0
        
        # Initialize border walls
        for i in range(MAZE_DIM):
            self.walls[i][0][3] = 1 # West border
            self.walls[i][MAZE_DIM-1][1] = 1 # East border
            self.walls[0][i][2] = 1 # South border
            self.walls[MAZE_DIM-1][i][0] = 1 # North border
            
    def _read_sensors(self):
        """Helper to read all sensors."""
        tof_l, tof_c, tof_r = uct_mouse.get_tof()
        lenc, renc = uct_mouse.get_encoders()
        sensors = uct_mouse._mouse.get_sensors()
        gyro = sensors.get('gyro', 0.0)
        return tof_l, tof_c, tof_r, lenc, renc, gyro

    def _update_walls(self, tof_l, tof_c, tof_r):
        """
        TODO: Update self.walls for the current cell (self.x, self.y)
        based on ToF sensor readings. Remember to also update the wall map
        for the adjacent cells (e.g., if there's a wall north of (x,y), then
        there's a wall south of (x, y+1)).
        """
        self.visited[self.y][self.x] = True
        # Student code here
        pass

    def turn_to(self, target_dir):
        """
        TODO: Turn the mouse from self.dir to target_dir in-place using closed-loop
        gyro feedback. Update self.dir once complete.
        """
        if self.dir == target_dir: return
        # Student code here
        pass

    def align_to_walls(self):
        """
        TODO: Optional but recommended. Fine-tune alignment in the cell using front
        and/or side walls to prevent drift accumulation.
        """
        # Student code here
        pass

    def move_forward(self):
        """
        TODO: Drive forward exactly one cell (CELL_LENGTH_M) using closed-loop control
        fusing encoders, gyro, and optionally side wall ToF sensors for centering.
        Update self.x and self.y once successfully transitioned.
        """
        # Student code here
        pass

    def find_nearest_unvisited(self):
        """
        TODO: Use Breadth-First Search (BFS) to find the shortest path from the
        current cell (self.x, self.y) to the nearest unvisited cell.
        Returns a list of coordinate tuples [(x1, y1), (x2, y2), ...] representing the path.
        """
        # Student code here
        return None

    def find_path_to_center(self):
        """
        TODO: Use BFS to find the shortest path from the current cell (self.x, self.y)
        to the center cells ([4,4], [4,5], [5,4], [5,5]).
        Returns a list of coordinate tuples [(x1, y1), (x2, y2), ...] representing the path.
        """
        # Student code here
        return None

    def solve(self):
        if not uct_mouse.init():
            return

        try:
            with open("polarity.txt", "r") as f:
                lines = f.read().strip().split(",")
                uct_mouse.set_polarity(int(lines[0]), int(lines[1]))
                if len(lines) >= 4:
                    uct_mouse.set_encoder_polarity(int(lines[2]), int(lines[3]))
        except Exception:
            uct_mouse.set_polarity(-1, -1)

        print("--- Milestone 2: 100% Maze Exploration ---")
        
        # 1. Phase 1: Explore the maze until all reachable cells are visited
        while True:
            tof_l, tof_c, tof_r, _, _, _ = self._read_sensors()
            self._update_walls(tof_l, tof_c, tof_r)
            
            path = self.find_nearest_unvisited()
            if not path:
                print("All reachable cells visited!")
                break
                
            # Take the next step along the path
            next_x, next_y = path[0]
            
            # Determine direction to face next cell
            target_dir = 0
            for d in range(4):
                if self.x + DX[d] == next_x and self.y + DY[d] == next_y:
                    target_dir = d
                    break
                    
            self.turn_to(target_dir)
            self.move_forward()

        # 2. Phase 2: Navigate to the center from current position
        print("Now navigating to the center...")
        while True:
            if self.x in [4, 5] and self.y in [4, 5]:
                print("Reached the center!")
                break
                
            path = self.find_path_to_center()
            if not path:
                print("Center not reachable!")
                break
                
            next_x, next_y = path[0]
            target_dir = 0
            for d in range(4):
                if self.x + DX[d] == next_x and self.y + DY[d] == next_y:
                    target_dir = d
                    break
            self.turn_to(target_dir)
            self.move_forward()

def main():
    solver = MazeSolver()
    solver.solve()

if __name__ == "__main__":
    main()
