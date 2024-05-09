"""Defines the MonteCarlo class."""
import json
import os
from multiprocessing import JoinableQueue, Process
from multiprocessing.managers import BaseManager
from time import process_time, time
import inspect
import numpy as np
import simplekml

from rocketpy._encoders import RocketPyEncoder
from rocketpy.plots.monte_carlo_plots import _MonteCarloPlots
from rocketpy.prints.monte_carlo_prints import _MonteCarloPrints
from rocketpy.simulation.flight import Flight
from rocketpy.simulation.sim_config.flight2serializer import \
    flightv1_serializer
from rocketpy.simulation.sim_config.run_sim import run_flight
from rocketpy.tools import (generate_monte_carlo_ellipses,
                            generate_monte_carlo_ellipses_coordinates)

# TODO: Let Functions and Flights be json serializable
# TODO: Create evolution plots to analyze convergence


class MonteCarlo:
    """Class to run a Monte Carlo simulation of a rocket flight.

    Attributes
    ----------
    filename : str
        When running a new simulation, this parameter represents the
        initial part of the export filenames. For example, if the value
        is 'filename', the exported output files will be named
        'filename.outputs.txt'. When analyzing the results of a
        previous simulation, this parameter should be set to the .txt
        file containing the outputs of the previous monte carlo analysis.
    environment : StochasticEnvironment
        The stochastic environment object to be iterated over.
    rocket : StochasticRocket
        The stochastic rocket object to be iterated over.
    flight : StochasticFlight
        The stochastic flight object to be iterated over.
    export_list : list
        The list of variables to export. If None, the default list will
        be used. Default is None. # TODO: improve docs to explain the
        default list, and what can be exported.
    inputs_log : list
        List of dictionaries with the inputs used in each simulation.
    outputs_log : list
        List of dictionaries with the outputs of each simulation.
    errors_log : list
        List of dictionaries with the errors of each simulation.
    num_of_loaded_sims : int
        Number of simulations loaded from output_file being currently used.
    results : dict
        Monte carlo analysis results organized in a dictionary where the keys
        are the names of the saved attributes, and the values are a list with
        all the result number of the respective attribute
    processed_results : dict
        Creates a dictionary with the mean and standard deviation of each
        parameter available in the results
    prints : _MonteCarloPrints
        Object with methods to print information about the monte carlo
        simulation.
    plots : _MonteCarloPlots
        Object with methods to plot information about the monte carlo
        simulation.
    """

    def __init__(
        self, filename, environment, rocket, flight, export_list=None, batch_path=None
    ):
        """
        Initialize a MonteCarlo object.

        Parameters
        ----------
        filename : str
            When running a new simulation, this parameter represents the
            initial part of the export filenames. For example, if the value
            is 'filename', the exported output files will be named
            'filename.outputs.txt'. When analyzing the results of a
            previous simulation, this parameter should be set to the .txt
            file containing the outputs of the previous monte carlo
            analysis.
        environment : StochasticEnvironment
            The stochastic environment object to be iterated over.
        rocket : StochasticRocket
            The stochastic rocket object to be iterated over.
        flight : StochasticFlight
            The stochastic flight object to be iterated over.
        export_list : list, optional
            The list of variables to export. If None, the default list will
            be used. Default is None. # TODO: improve docs to explain the
            default list, and what can be exported.
        batch_path : str, optional
            Path to the batch folder to be used in the simulation. Export file
            will be saved in this folder. Default is None.

        Returns
        -------
        None
        """
        # Save and initialize parameters
        self.filename = filename
        self.environment = environment
        global StoEnv
        StoEnv = environment
        self.rocket = rocket
        self.flight = flight
        self.export_list = []
        self.inputs_log = []
        self.outputs_log = []
        self.errors_log = []
        self.num_of_loaded_sims = 0
        self.results = {}
        self.processed_results = {}
        self.prints = _MonteCarloPrints(self)
        self.plots = _MonteCarloPlots(self)
        self._inputs_dict = {}
        self._last_print_len = 0  # used to print on the same line
        self.batch_path = batch_path

        # Checks export_list
        self.export_list = self.__check_export_list(export_list)

        try:
            self.import_inputs()
        except FileNotFoundError:
            self._input_file = f"{filename}.inputs.txt"

        try:
            self.import_outputs()
        except FileNotFoundError:
            self._output_file = f"{filename}.outputs.txt"

        try:
            self.import_errors()
        except FileNotFoundError:
            self._error_file = f"{filename}.errors.txt"

    def simulate(self, number_of_simulations, append=False, parallel=False):
        """
        Runs the monte carlo simulation and saves all data.

        Parameters
        ----------
        number_of_simulations : int
            Number of simulations to be run, must be non-negative.
        append : bool, optional
            If True, the results will be appended to the existing files. If
            False, the files will be overwritten. Default is False.

        Returns
        -------
        None
        """
        if parallel:
            self._run_in_parallel(number_of_simulations)
        else:
            # Create data files for inputs, outputs and error logging
            open_mode = "a" if append else "w"
            input_file = open(self._input_file, open_mode, encoding="utf-8")
            output_file = open(self._output_file, open_mode, encoding="utf-8")
            error_file = open(self._error_file, open_mode, encoding="utf-8")

            # initialize counters
            self.number_of_simulations = number_of_simulations
            self.iteration_count = self.num_of_loaded_sims if append else 0
            self.start_time = time()
            self.start_cpu_time = process_time()

            # Begin display
            print("Starting monte carlo analysis", end="\r")

            try:
                while self.iteration_count < self.number_of_simulations:
                    self.__run_single_simulation(input_file, output_file)
            except KeyboardInterrupt:
                print("Keyboard Interrupt, files saved.")
                error_file.write(
                    json.dumps(self._inputs_dict, cls=RocketPyEncoder) + "\n"
                )
                self.__close_files(input_file, output_file, error_file)
            except Exception as error:
                print(f"Error on iteration {self.iteration_count}: {error}")
                error_file.write(
                    json.dumps(self._inputs_dict, cls=RocketPyEncoder) + "\n"
                )
                self.__close_files(input_file, output_file, error_file)
                raise error

            self.__finalize_simulation(input_file, output_file, error_file)

    def _run_in_parallel(self, number_of_simulations, n_workers=None):
        """Runs the monte carlo simulation in parallel."""
        processes = []

        if n_workers is None:
            n_workers = os.cpu_count()

        with MonteCarloManager() as manager:
            # initialize queue
            simulation_queue = manager.JoinableQueue()
            sim_counter = manager.SimCounter()

            start_queue_time = process_time()
            # build queue
            self._build_queue(number_of_simulations, simulation_queue)
            end_queue_time = process_time()

            print(
                f"Simulation took {end_queue_time - start_queue_time} seconds to build queue."
            )

            print("Starting monte carlo analysis", end="\r")
            print(f"Number of simulations: {number_of_simulations}")

            # Creates 10 processes then starts them
            for i in range(n_workers):
                p = Process(
                    target=self._run_simulation_worker,
                    args=(i+1, simulation_queue, sim_counter, self.batch_path),
                )
                processes.append(p)

            # Joins all the processes
            for p in processes:
                p.start()
            for p in processes:
                p.join()

            print("-" * 80 + "All workers joined, simulation complete.")

    def _build_queue(self, number_of_simulations, simulation_queue):
        dummy_env = self.environment.create_object()

        """Builds a queue with the simulations to be run."""
        for i in range(number_of_simulations):
            rocket = self.rocket.create_object()
            rail_length = self.flight._randomize_rail_length()
            inclination = self.flight._randomize_inclination()
            heading = self.flight._randomize_heading()
            initial_solution = self.flight.initial_solution
            terminate_on_apogee = self.flight.terminate_on_apogee

            flight = Flight(
                rocket=rocket,
                environment=dummy_env,
                rail_length=rail_length,
                inclination=inclination,
                heading=heading,
                initial_solution=initial_solution,
                terminate_on_apogee=terminate_on_apogee,
                simulate=False,
            )

            input_parameters = flightv1_serializer(
                flight, f"Simulation_{i}", return_dict=True
            )

            # self._inputs_dict = dict(
            #     item
            #     for d in [
            #         self.environment.last_rnd_dict,
            #         self.rocket.last_rnd_dict,
            #         self.flight.last_rnd_dict,
            #     ]
            #     for item in d.items()
            # )

            simulation_queue.put((input_parameters))

    @staticmethod
    def _run_simulation_worker(i, queue, sim_counter, batch_path):
        """Runs a simulation from a queue."""

        try:
            while True:
                if queue.empty():
                    break
                parameters = queue.get()
                sim_idx = sim_counter.increment()

                sim_start = process_time()
                env = StoEnv.create_object()

                flight = run_flight(parameters, env)
                flight.post_process()
                sim_end = process_time()

                flight_results = MonteCarlo.attribute_path(flight)
                
                print(
                    "-" * 80
                    + f"\nSimulation {sim_idx} took {sim_end - sim_start} seconds to run."
                )
                
                print(flight_results.keys())
                print(flight_results['Flight'].keys())

        except Exception as error:
            print(f"Worker {i} failed with the exception:\n{error}")
        finally:
            print(f"Worker {i} finished.")

    def __run_single_simulation(self, input_file, output_file):
        """Runs a single simulation and saves the inputs and outputs to the
        respective files."""
        # Update iteration count
        self.iteration_count += 1
        # Run trajectory simulation
        monte_carlo_flight = Flight(
            rocket=self.rocket.create_object(),
            environment=self.environment.create_object(),
            rail_length=self.flight._randomize_rail_length(),
            inclination=self.flight._randomize_inclination(),
            heading=self.flight._randomize_heading(),
            initial_solution=self.flight.initial_solution,
            terminate_on_apogee=self.flight.terminate_on_apogee,
        )

        self._inputs_dict = dict(
            item
            for d in [
                self.environment.last_rnd_dict,
                self.rocket.last_rnd_dict,
                self.flight.last_rnd_dict,
            ]
            for item in d.items()
        )

        # Export inputs and outputs to file
        self.__export_flight_data(
            flight=monte_carlo_flight,
            inputs_dict=self._inputs_dict,
            input_file=input_file,
            output_file=output_file,
        )

        average_time = (process_time() - self.start_cpu_time) / self.iteration_count
        estimated_time = int(
            (self.number_of_simulations - self.iteration_count) * average_time
        )
        self.__reprint(
            f"Current iteration: {self.iteration_count:06d} | "
            f"Average Time per Iteration: {average_time:.3f} s | "
            f"Estimated time left: {estimated_time} s",
            end="\r",
            flush=True,
        )

    def __close_files(self, input_file, output_file, error_file):
        """Closes all the files."""
        input_file.close()
        output_file.close()
        error_file.close()

    def __finalize_simulation(self, input_file, output_file, error_file):
        """Finalizes the simulation, closes the files and prints the results."""
        final_string = (
            f"Completed {self.iteration_count} iterations. Total CPU time: "
            f"{process_time() - self.start_cpu_time:.1f} s. Total wall time: "
            f"{time() - self.start_time:.1f} s\n"
        )

        self.__reprint(final_string + "Saving results.", flush=True)

        # close files to guarantee saving
        self.__close_files(input_file, output_file, error_file)

        # resave the files on self and calculate post simulation attributes
        self.input_file = f"{self.filename}.inputs.txt"
        self.output_file = f"{self.filename}.outputs.txt"
        self.error_file = f"{self.filename}.errors.txt"

        print(f"Results saved to {self._output_file}")

    def __export_flight_data(
        self,
        flight,
        inputs_dict,
        input_file,
        output_file,
    ):
        """Exports the flight data to the respective files."""
        # Construct the dict with the results from the flight
        results = {
            export_item: getattr(flight, export_item)
            for export_item in self.export_list
        }

        # Write flight setting and results to file
        input_file.write(json.dumps(inputs_dict, cls=RocketPyEncoder) + "\n")
        output_file.write(json.dumps(results, cls=RocketPyEncoder) + "\n")

    def __check_export_list(self, export_list):
        """Checks if the export_list is valid and returns a valid list. If no
        export_list is provided, the default list is used."""
        standard_output = set(
            {
                "apogee",
                "apogee_time",
                "apogee_x",
                "apogee_y",
                # "apogee_freestream_speed",
                "t_final",
                "x_impact",
                "y_impact",
                "impact_velocity",
                # "initial_stability_margin", # Needs to implement it!
                # "out_of_rail_stability_margin", # Needs to implement it!
                "out_of_rail_time",
                "out_of_rail_velocity",
                # "max_speed",
                "max_mach_number",
                # "max_acceleration_power_on",
                "frontal_surface_wind",
                "lateral_surface_wind",
            }
        )
        exportables = set(
            {
                "inclination",
                "heading",
                "effective1rl",
                "effective2rl",
                "out_of_rail_time",
                "out_of_rail_time_index",
                "out_of_rail_state",
                "out_of_rail_velocity",
                "rail_button1_normal_force",
                "max_rail_button1_normal_force",
                "rail_button1_shear_force",
                "max_rail_button1_shear_force",
                "rail_button2_normal_force",
                "max_rail_button2_normal_force",
                "rail_button2_shear_force",
                "max_rail_button2_shear_force",
                "out_of_rail_static_margin",
                "apogee_state",
                "apogee_time",
                "apogee_x",
                "apogee_y",
                "apogee",
                "x_impact",
                "y_impact",
                "z_impact",
                "impact_velocity",
                "impact_state",
                "parachute_events",
                "apogee_freestream_speed",
                "final_static_margin",
                "frontal_surface_wind",
                "initial_static_margin",
                "lateral_surface_wind",
                "max_acceleration",
                "max_acceleration_time",
                "max_dynamic_pressure_time",
                "max_dynamic_pressure",
                "max_mach_number_time",
                "max_mach_number",
                "max_reynolds_number_time",
                "max_reynolds_number",
                "max_speed_time",
                "max_speed",
                "max_total_pressure_time",
                "max_total_pressure",
                "t_final",
            }
        )
        if export_list:
            for attr in set(export_list):
                if not isinstance(attr, str):
                    raise TypeError("Variables in export_list must be strings.")

                # Checks if attribute is not valid
                if attr not in exportables:
                    raise ValueError(
                        f"Attribute '{attr}' can not be exported. Check export_list."
                    )
        else:
            # No export list provided, using default list instead.
            export_list = standard_output

        return export_list

    def __reprint(self, msg, end="\n", flush=False):
        """Prints a message on the same line as the previous one and replaces
        the previous message with the new one, deleting the extra characters
        from the previous message.

        Parameters
        ----------
        msg : str
            Message to be printed.
        end : str, optional
            String appended after the message. Default is a new line.
        flush : bool, optional
            If True, the output is flushed. Default is False.

        Returns
        -------
        None
        """

        len_msg = len(msg)
        if len_msg < self._last_print_len:
            msg += " " * (self._last_print_len - len_msg)
        else:
            self._last_print_len = len_msg

        print(msg, end=end, flush=flush)

    @property
    def input_file(self):
        """String containing the filepath of the input file"""
        return self._input_file

    @input_file.setter
    def input_file(self, value):
        """Setter for input_file. Sets/updates inputs_log."""
        self._input_file = value
        self.set_inputs_log()

    @property
    def output_file(self):
        """String containing the filepath of the output file"""
        return self._output_file

    @output_file.setter
    def output_file(self, value):
        """Setter for input_file. Sets/updates outputs_log, num_of_loaded_sims,
        results, and processed_results."""
        self._output_file = value
        self.set_outputs_log()
        self.set_num_of_loaded_sims()
        self.set_results()
        self.set_processed_results()

    @property
    def error_file(self):
        """String containing the filepath of the error file"""
        return self._error_file

    @error_file.setter
    def error_file(self, value):
        """Setter for input_file. Sets/updates inputs_log."""
        self._error_file = value
        self.set_errors_log()

    # setters for post simulation attributes
    def set_inputs_log(self):
        """Sets inputs_log from a file into an attribute for easy access"""
        self.inputs_log = []
        with open(self.input_file, mode="r", encoding="utf-8") as rows:
            for line in rows:
                self.inputs_log.append(json.loads(line))

    def set_outputs_log(self):
        """Sets outputs_log from a file into an attribute for easy access"""
        self.outputs_log = []
        with open(self.output_file, mode="r", encoding="utf-8") as rows:
            for line in rows:
                self.outputs_log.append(json.loads(line))

    def set_errors_log(self):
        """Sets errors_log log from a file into an attribute for easy access"""
        self.errors_log = []
        with open(self.error_file, mode="r", encoding="utf-8") as errors:
            for line in errors:
                self.errors_log.append(json.loads(line))

    def set_num_of_loaded_sims(self):
        """Number of simulations loaded from output_file being currently used."""
        with open(self.output_file, mode="r", encoding="utf-8") as outputs:
            self.num_of_loaded_sims = sum(1 for _ in outputs)

    def set_results(self):
        """Monte carlo results organized in a dictionary where the keys are the
        names of the saved attributes, and the values are a list with all the
        result number of the respective attribute"""
        self.results = {}
        for result in self.outputs_log:
            for key, value in result.items():
                if key in self.results:
                    self.results[key].append(value)
                else:
                    self.results[key] = [value]

    def set_processed_results(self):
        """Creates a dictionary with the mean and standard deviation of each
        parameter available in the results"""
        self.processed_results = {}
        for result, values in self.results.items():
            mean = np.mean(values)
            stdev = np.std(values)
            self.processed_results[result] = (mean, stdev)

    def import_outputs(self, filename=None):
        """Import monte carlo results from .txt file and save it into a
        dictionary.

        Parameters
        ----------
        filename : str
            Name or directory path to the file to be imported. If none,
            self.filename will be used.

        Returns
        -------
        None
        """
        filepath = filename if filename else self.filename

        try:
            with open(f"{filepath}.outputs.txt", "r+", encoding="utf-8"):
                self.output_file = f"{filepath}.outputs.txt"
        except FileNotFoundError:
            with open(filepath, "r+", encoding="utf-8"):
                self.output_file = filepath

        print(
            f"A total of {self.num_of_loaded_sims} simulations results were "
            f"loaded from the following output file: {self.output_file}\n"
        )

    def import_inputs(self, filename=None):
        """Import monte carlo results from .txt file and save it into a
        dictionary.

        Parameters
        ----------
        filename : str
            Name or directory path to the file to be imported. If none,
            self.filename will be used.

        Returns
        -------
        None
        """
        filepath = filename if filename else self.filename

        try:
            with open(f"{filepath}.inputs.txt", "r+", encoding="utf-8"):
                self.input_file = f"{filepath}.inputs.txt"
        except FileNotFoundError:
            with open(filepath, "r+", encoding="utf-8"):
                self.input_file = filepath

        print(f"The following input file was imported: {self.input_file}")

    def import_errors(self, filename=None):
        """Import monte carlo results from .txt file and save it into a
        dictionary.

        Parameters
        ----------
        filename : str
            Name or directory path to the file to be imported. If none,
            self.filename will be used.

        Returns
        -------
        None
        """
        filepath = filename if filename else self.filename

        try:
            with open(f"{filepath}.errors.txt", "r+", encoding="utf-8"):
                self.error_file = f"{filepath}.errors.txt"
        except FileNotFoundError:
            with open(filepath, "r+", encoding="utf-8"):
                self.error_file = filepath
        print(f"The following error file was imported: {self.error_file}")

    def import_results(self, filename=None):
        """Import monte carlo results from .txt file and save it into a
        dictionary.

        Parameters
        ----------
        filename : str
            Name or directory path to the file to be imported. If none,
            self.filename will be used.

        Returns
        -------
        None
        """
        # select file to use
        filepath = filename if filename else self.filename

        self.import_outputs(filename=filepath)
        self.import_inputs(filename=filepath)
        self.import_errors(filename=filepath)

    def export_ellipses_to_kml(
        self,
        filename,
        origin_lat,
        origin_lon,
        type="all",
        resolution=100,
        color="ff0000ff",
    ):
        """Generates a KML file with the ellipses on the impact point.

        Parameters
        ----------
        results : dict
            Contains results from the Monte Carlo simulation.
        filename : String
            Name to the KML exported file.
        origin_lat : float
            Latitude coordinate of Ellipses' geometric center, in degrees.
        origin_lon : float
            Latitude coordinate of Ellipses' geometric center, in degrees.
        type : String
            Type of ellipses to be exported. Options are: 'all', 'impact' and
            'apogee'. Default is 'all', it exports both apogee and impact
            ellipses.
        resolution : int
            Number of points to be used to draw the ellipse. Default is 100.
        color : String
            Color of the ellipse. Default is 'ff0000ff', which is red.
            Kml files use an 8 digit HEX color format, see its docs.

        Returns
        -------
        None
        """

        (
            impact_ellipses,
            apogee_ellipses,
            *_,
        ) = generate_monte_carlo_ellipses(self.results)
        outputs = []

        if type == "all" or type == "impact":
            outputs = outputs + generate_monte_carlo_ellipses_coordinates(
                impact_ellipses, origin_lat, origin_lon, resolution=resolution
            )

        if type == "all" or type == "apogee":
            outputs = outputs + generate_monte_carlo_ellipses_coordinates(
                apogee_ellipses, origin_lat, origin_lon, resolution=resolution
            )

        # Prepare data to KML file
        kml_data = [[(coord[1], coord[0]) for coord in output] for output in outputs]

        # Export to KML
        kml = simplekml.Kml()

        for i in range(len(outputs)):
            if (type == "all" and i < 3) or (type == "impact"):
                ellipse_name = "Impact σ" + str(i + 1)
            elif type == "all" and i >= 3:
                ellipse_name = "Apogee σ" + str(i - 2)
            else:
                ellipse_name = "Apogee σ" + str(i + 1)

            mult_ell = kml.newmultigeometry(name=ellipse_name)
            mult_ell.newpolygon(
                outerboundaryis=kml_data[i],
                name="Ellipse " + str(i),
            )
            # Setting ellipse style
            mult_ell.tessellate = 1
            mult_ell.visibility = 1
            mult_ell.style.linestyle.color = color
            mult_ell.style.linestyle.width = 3
            mult_ell.style.polystyle.color = simplekml.Color.changealphaint(
                100, simplekml.Color.blue
            )

        kml.save(filename)

    def info(self):
        """Print information about the monte carlo simulation."""
        self.prints.all()

    def all_info(self):
        """Print and plot information about the monte carlo simulation
        and its results.

        Returns
        -------
        None
        """
        self.info()
        self.plots.ellipses()
        self.plots.all()
    
    @staticmethod        
    def attribute_path(obj, max_depth=1):
        # This dictionary will hold the attribute paths and their values.
        result = {}
        
        # Helper function to process each object
        def recurse(obj, parent, depth):
            # We assume all objects passed into here are class instances
            # We get the name of the class of the object
            class_name = obj.__class__.__name__
            # Create a dictionary for this class if not already created
            if class_name not in parent:
                parent[class_name] = {}
            
            # Iterate through each attribute of the object
            for attr_name, attr_value in vars(obj).items():
                # Check if the attribute is an instance of a class
                if hasattr(attr_value, '__dict__') and depth < max_depth:
                    # Recursive case: attribute is a class instance
                    recurse(attr_value, parent[class_name], depth=depth+1)
                elif isinstance(attr_value, (np.ndarray, list, int, float)):
                    # Base case: attribute is a primitive, store it
                    parent[class_name][attr_name] = attr_value

        # Start the recursion with the initial object
        recurse(obj, result, depth=1)
        return result


class MonteCarloManager(BaseManager):
    def __init__(self):
        super().__init__()
        self.register('JoinableQueue', JoinableQueue)
        self.register('SimCounter', SimCounter)

class SimCounter:
    def __init__(self):
        self.count = 0

    def increment(self) -> int:
        self.count += 1
        return self.count

    def get_count(self) -> int:
        return self.count