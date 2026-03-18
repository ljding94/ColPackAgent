import os
import json
import numpy as np
from colpack.init import create_initial_config
from colpack.compress import compress_system
from colpack.sample import sample_system
from colpack.analyze import analyze_main



# generate the simulation config for a base simulation run,
def generate_base_config():
    '''
    base case, output mainly particle mixture and shape information for later planning usage
    this define the system of interest, such as binary sphere, sphere/capsul mixture, etc. the config can be a json file listing the particle types and their shape parameters, and the init gsd file for the base initial configuration
    this fix the particle type for the entire class of simulation run
    '''

# planning all of the simulation run, based on variation of the base simulation run
def plan_simulaiton_runs():
    '''
    this funtion will add simulation parameters entry into the planning.csv (might not be good for structured shape parameters, maybe pd) file
    variation will be based on the base simulation config,
    for simplicity each time we change one of the parameters, such as: particle number, particle shape parameter, number density etc.
    '''


# excute simulation workflow for each simulation run
def excute_simulation_workflow():
    '''
    this function will excute the simulation workflow for every entry of the planned simulation parameters
    '''


