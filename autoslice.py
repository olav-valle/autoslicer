import argparse
import configparser
import os
import subprocess
import tempfile

import numpy as np
from stl import Mesh


class AutoSlicer:
    # Select slicer parameters based on unprintability > treshold
    treshold_supports = 1.0
    treshold_brim = 2.0

    tweaker_path = ''

    def __init__(self, slicer_path, config_path, tweaker_path):
        """Initialize AutoSlicer.
        
        Keyword arguments:
        slicer_path -- location of PrusaSlicer executable. Should be .AppImage or prusa-slicer-console.exe
        config_path -- location of printer config file
        """
        self.slicer = slicer_path
        self.config = config_path
        self.tweaker = tweaker_path


    def __tweakFile(self, input_file, tmpdir):
        # Runs Tweaker.py from https://github.com/ChristophSchranz/Tweaker-3

        try:
            output_file = os.path.join(tmpdir, "tweaked.stl")
            print('autoslice.__tweakfile: output_file:', output_file)
            curr_path = os.path.dirname(os.path.abspath(__file__))
            print('autoslice.__tweakfile: curr_path:', curr_path)
            if os.name == "nt":
                print('autoslice.__tweakfile: OS is windows')
                python_path = os.path.join(curr_path, "venv", "Scripts", "python")
            else:
                print('autoslice.__tweakfile: os is unix-ish')
                python_path = os.path.join(curr_path, "venv", "bin", "python")
                print('autoslice.__tweakfile: python_path:',python_path )
            tweaker_path = os.path.join(curr_path, self.tweaker, "Tweaker.py")
            print('autoslice.__tweakfile: tweaker_path:', tweaker_path)

            result = subprocess.run([python_path, tweaker_path, "-i", input_file, "-o", output_file, "-x", "-vb"]
                                    , capture_output=True, text=True).stdout
            print('autoslice.__tweakfile: result = subprocess.run:', result)

            # Get "unprintability" from stdout
            _, temp = result.splitlines()[-5].split(":")
            unprintability = str(round(float(temp.strip()), 2))
            print("Unprintability: " + unprintability)
            #print(result)
            print(output_file)
            return output_file, unprintability
        except subprocess.SubprocessError as e:
            print(e)
            print("Couldn't run tweaker on file " + self.input_file)


    def __adjustHeight(self, input_file, tmpdir):
        # Move STL coordinates so Zmin = 0
        # This avoids errors in PrusaSlicer if Z is above/below the build plate
        try:
            output_file = os.path.join(tmpdir, "translated.stl")
            my_mesh = Mesh.from_file(input_file)
            print("Z min:", my_mesh.z.min())
            print("Z max:", my_mesh.z.max())
            translation = np.array([0, 0, -my_mesh.z.min()])
            my_mesh.translate(translation)
            print("Translated, new Z min:", my_mesh.z.min())
            my_mesh.save(output_file)
            return output_file
        except:
            print("Couldn't adjust height of file " + self.input_file)


    def __runSlicer(self, input, output_path, unprintability):
        # Run PrusaSlicer
        print('autoslice.__runSlicer: preparing to start PrusaSlicer')
        print('autoslice.__runSlicer: input = ', input)
        print('autoslice.__runSlicer: output_path = ', output_path)
        print('autoslice.__runSlicer: unprintability = ', unprintability)
        cwd = os.getcwd()
        print('autoslice.__runSlicer: cwd = ', cwd)

        # Get filename with mostly alphanumeric characters
        # Avoids errors with octopi upload due to invalid characters in filename
        filename, _ = os.path.basename(self.input_file).rsplit(".", 1)
        filename = self.__cleanName(filename)

        output_file = os.path.join(
            output_path,
            (filename + "_U" + str(unprintability) + "_{print_time}" ".gcode")
            )
        
        # Form command to run
        # Example: prusa-slicer-console.exe --load MK3Sconfig.ini -g -o outputFiles/sliced.gcode inputFiles/input.gcode
        cmd = [self.slicer, "--load", self.config]

        if float(unprintability) > self.treshold_brim:
            cmd.extend(["--brim-width", "5", "--skirt-distance", "6"])
        if float(unprintability) > self.treshold_supports:
            cmd.append("--support-material")

        cmd.extend(["-g", "-o", output_file, input])
        try:
            print('autoslice.__runSlicer: command string cmd = \n', cmd)
            subprocess.run(cmd, check=True)
        except:
            # subprocess.SubprocessError as e:
            # print(e)
            print('autoslice.__runSlicer: command string cmd failed:', cmd)
            print("autoslice.__runSlicer: Couldn't slice file " + self.input_file)
        return 


    def __cleanName(self, name):
        # Removes/replaces chars to get mostly alphanumeric characters + ().-_
        replace_dict = { " ":"_", ",":".", "æ":"ae", "Æ":"AE", "ø":"o", "Ø":"O", "å":"a", "Å":"A"}
        for i, j in replace_dict.items():
            name = name.replace(i, j)

        delete_list = ["!", '"', "'", "#", "¤", "%", "&", "/", "=", "\\", "+", "`", 
            "´", "~", "^", "¨", "*", "{", "}", "[", "]", "@", "£", "$", "€", ";", ":", "<", ">", "|", "µ", "§"]
        for i in delete_list:
            name = name.replace(i, "")

        return name


    def slice(self, input, output):
        """Rotates and slices file in optimal orientation

        Keyword arguments:
        input -- file to slice (STL or 3MF)
        output -- path to place output GCODE
        """
        self.input_file = input
        with tempfile.TemporaryDirectory() as temp_directory:
            print("autoslicer.main.slice: Temp. dir:", temp_directory)
            tweaked_file, unprintability = self.__tweakFile(self.input_file, temp_directory)
            print("autoslicer.main.slice tweak_file")
            translatedFile = self.__adjustHeight(tweaked_file, temp_directory)
            self.__runSlicer(translatedFile, output, unprintability)


# For use as commandline tool:
if __name__ == "__main__":
    # Get command line arguments
    parser = argparse.ArgumentParser(description="Autoslicer")
    parser.add_argument("inputFile", help="The file to be sliced (STL/3MF)")
    parser.add_argument("printerConfig", help="Select printer config. file from PrusaSlicer")
    parser.add_argument("slicer", help="PrusaSlicer location")
    parser.add_argument("-o", "--output", help="Output folder (default is current location)", default=os.getcwd())
    args = parser.parse_args()

    config = configparser.ConfigParser()
    config.read("./Config/config.ini")
    tweaker = config["PATHS"]["tweaker"]

    # Validate args:
    # Check if input file exists
    if not os.path.exists(args.inputFile):
        print("Error: input file not found")
        print(os.path.abspath(args.inputFile))
        # Exit program - no valid file!
        exit()
    # Check if file extension is correct - STL or 3MF
    _, extension = args.inputFile.rsplit(".", 1)
    if not extension.lower() in ["stl", "3mf"]:
        print("Error: input file has invalid format")
        print("Files need to be .stl or .3mf, not ." + extension.lower())
        exit()
    # Check if output folder exists
    # If not - create it
    if not os.path.exists(args.output):
        print("Output path not found, creating " + os.path.abspath(args.output))
        os.mkdir(os.path.abspath(args.output))
    # Check if slicer exists
    if not os.path.exists(args.slicer):
        print("Error: slicer not found at", os.path.abspath(args.slicer))
    # Check if config file exists
    if not os.path.exists(args.printerConfig):
        print("Error: printer config file not found at", os.path.abspath(args.printerConfig))

    autoslicer = AutoSlicer(slicer_path=args.slicer, config_path=args.printerConfig, tweaker_path=tweaker)
    input_file = os.path.abspath(args.inputFile)
    output_path = os.path.abspath(args.output)
    autoslicer.slice(input_file, output_path)