Requirements
============

Usually, you can skip this part if you have an updated version of Python running on a normal computer.
But read further if this is not your case!

Python Version
--------------

RocketPy supports Python 3.7 and above.
Support for Python 3.11 is still limited by some dependencies.
Sorry, there are currently no plans to support earlier versions.
If you really need to run RocketPy on Python 3.6 or earlier, feel free to submit an issue and we will see what we can do!

Required Packages
-----------------

The following packages are needed in order to run RocketPy:

- requests
- Numpy >= 1.0
- Scipy >= 1.0
- Matplotlib >= 3.0
- netCDF4 >= 1.4
- windrose >= 1.6.8
- requests
- pytz
- simplekml
- ipywidgets >= 7.6.3
- jsonpickle
- vedo

 
All of these packages, are automatically installed when RocketPy is installed using either ``pip`` or ``conda``.
However, in case the user wants to install these packages manually, they can do so by following the instructions bellow.

Installing Required Packages Using ``pip``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The packages needed can be installed via ``pip`` by running the following lines of code in your preferred terminal, assuming pip is added to the PATH:

.. code-block:: shell

    pip install "numpy>=1.0" 
    pip install "scipy>=1.0"
    pip install "matplotlib>=3.0"
    pip install "netCDF4>=1.4"
    pip install "windrose >= 1.6.8"
    pip install "ipywidgets>=7.6.3"
    pip install requests
    pip install pytz
    pip install simplekml
    pip install jsonpickle

Installing Required Packages Using ``conda``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Numpy, Scipy, Matplotlib and requests come with Anaconda, but Scipy might need updating.
The nedCDF4 package can be installed if there is interest in importing weather data from netCDF files.
To update Scipy and install netCDF4 using Conda, the following code is used:

.. code-block:: shell

    conda install "scipy>=1.0"
    conda install -c anaconda "netcdf4>=1.4"


Optional Packages
-----------------

Optionally, you can install timezonefinder to allow for automatic timezone detection when performing Enviornment Analysis.
This can be done by running the following line of code in your preferred terminal:

.. code-block:: shell

    pip install timezonefinder

Keep in mind that this package is not required to run RocketPy, but it can be useful if you want to perform Environment Analysis.
Furthermore, timezonefinder can only be used with Python 3.8+.

Useful Packages
---------------

Although `Jupyter Notebooks <http://jupyter.org/>`_ are by no means required to run RocketPy, they can be a handy tool!
All of are examples are written using Jupyter Notebooks so that you can follow along easily.
They already come with Anaconda builds, but can also be installed separately using pip:

.. code-block:: shell

    pip install jupyter
