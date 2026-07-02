import pdb
import sys
import os
import math
import argparse
import random
import json
pyEvtSimDir = '/Users/profnicol/pyevtsim'
sys.path.append(pyEvtSimDir)

from vrt import VT, VTZero, PriPair
from rng import sampleExpon, sampleInt, sampleRV
from model_queue import ModelQueue
from stats import Trace
from evt import EvtList, EvtFunc, EvtMgr

ARRIVAL_RATE = 0.0
SEED = 123456
serving_customers = 0
SERVING_LIMIT = 10
TERMINATION = 0.0
MAX_ORDER = 5
MIN_ORDER = 5

Topo_dict = {}
custStrm = None
pay_station = None
pickup_station = None
MenuStations = []

customerCnt  = 0
def NxtCustomerID():
    global customerCnt
    customerCnt += 1
    return customerCnt


# Customer entity is created specifying a name, the minimum number of items to be ordered,
# the maximum number of items to be ordered


class Customer():
    def __init__(self, min_order, max_order: int):
        # uniformly sample from range of possible order sizes
        self.num_items = sampleInt(min_order, max_order)

        # unique customer ID
        self.ID = NxtCustomerID()
    
        # print(f"Customer {self.ID} arrives at time {EvtMgr.NowInSecs()}")

    def customerID(self) -> int:
        return self.ID

# CustomerStream is the process of generating arrivals to the system.
# Poisson arrivals are simulated, but if there are too many admitted
# but as-yet unprocessed customers, the arrival is dropped.


class CustomerStream():
    def __init__(self, name, arrival_rate, max_customers):
        """
        :param name: string name for this object
        :param arrival_rate: floating point rate of car arrivals per second
        :param max_customers: maximum number of customers permitted in system concurrently
        """

        # remember text identifier
        self.name = name

        # Remember the arrival rate, will be needed every time
        # this object schedules the arrival of the next customer.
        #
        self.arrival_rate = arrival_rate

        # Remember the maximum number of customers the model 
        # allows to be in the system concurrently
        #
        self.max_customers = max_customers

        # Accumulate the total number of arrivals during simulation
        self.arrivals = 0

        # Accumulated the total number of arrivals not admitted.
        self.discouraged_arrivals = 0

        # Keep track of number of customers in processing, to be
        # compared with self.max_customers when a new customer arrives
        #
        self.serving_customers = 0

        # Create space for the menu stations that are the first step in the system.
        self.menu_stations = []

        # Build a trace of customers, when admitted and when departed.
        self.trace = Trace("customer")

    # addOutput stores a pointer to a menu station that receives customers.
    # Separated from the CustomerStream constructor call to avoid forcing
    # an order of construction on the various simulation model entities

    def addOutput(self, ms):
        self.menu_stations.append(ms)

    # NewCustomer handles the possibility of including a new arrival into the system, either rejecting it or
    # calling code that passes it to a menu station, and schedules the next
    # arrival.  If the system is full it just schedules the next arrival.

    def NewCustomer(self, only_schedule, none):

        # The parameter 'only_schedule' is True on an initial call
        # made just to schedule the first arrival.  Every subsequent
        # call will treat the event execution as the arrival of a customer.
        # 
        if not only_schedule:
            if self.serving_customers == self.max_customers:
                self.discouraged_arrivals += 1
            else:
                # The customer can be admitted to the system.
                self.arrivals += 1

                # Create the customer instance.
                cust = Customer(MIN_ORDER, MAX_ORDER)

                # Record the customer's arrival time.
                self.AddObs("start", EvtMgr.NowInSecs(), cust.customerID())

                # Choose a menu station and deliver the customer to it.
                self.deliverCustomer(cust)

        # Schedule the next arrival
        # sampling from an exponential probability distribution
        # with rate give at the CustomerStream construction.
        #    Sample the number of seconds until the next arrival,
        # then transform into virtual time format.
        #
        inter_arrival_time = sampleExpon(self.arrival_rate)
        vt_inter_arrival_time = VT.from_secs(inter_arrival_time, pri=1)

        # Frame the scheduling request in an EvtFunc for subsequent scheduling.
        evt_func = EvtFunc(False, None, self.NewCustomer)

        # Schedule the next arrival.
        EvtMgr.AddEvt(evt_func, vt_inter_arrival_time,
                      desc=f"{self.name} NewCustomer generation")

    # deliverCustomer selects a menu board with fewest customers in queue or being served
    # and delivers the new customer to it.

    def deliverCustomer(self, cust):
        # choose the menu board with fewest in line.
        best_ms = None
        for ms in self.menu_stations:
            if best_ms is None or (ms.InSystem() < best_ms.InSystem()):
                best_ms = ms

        # custArrival method of menu station handles a new customer arrival.
        best_ms.custArrival(cust)

    # departCust is called when a customer that has been admitted to the system
    # finally departs. The method just records the event, and removes it from the total number
    # of customers being served.

    def departCust(self, cust):
        self.AddObs("stop", EvtMgr.NowInSecs(), cust.customerID())
        self.serving_customers -= 1

    # AddObs registers an observation to the object's own trace list.

    def AddObs(self, msg, time, ID):
        self.trace.AddObs(msg, time, ID)

    # ReportArrivals is called when the simulation ends to report on arrivals.

    def ReportArrivals(self):
        print(f"total arrivals = {self.arrivals}, \
              discouraged arrivals = {self.discouraged_arrivals}")
            

# A MenuStation instance models where a customer places an order.
# The distribution parameters given are for a per-item ordering cost,
# a time for each item sampled from that distribution.


class MenuStation(ModelQueue):
    def __init__(self, name, service_mu, service_sigma, service_dist):

        # Tell the ModelQueue representation of the function to use
        # when sampling service.

            
        super().__init__(name, self.menuService)

        # remember the parameters
        self.service_mu = service_mu
        self.service_sigma = service_sigma
        self.service_dist = service_dist

    def menuService(self, cust):
        # service time
        service = 0.0
        for idx in range(0, cust.num_items):
            service += sampleRV(
                self.service_mu, self.service_sigma, self.service_dist)
        return service

# The PayStation represents where drive-thru customers advance to pay for the
# meal they ordered at the MenuStation.   The time delay associated with paying
# for the meal is modeled as being unrelated to the number of items ordered.
# The constructor is passed parameters describing the distribution to
# draw from when sampling that time when a customer arrives to pay.

class PayStation(ModelQueue):

    def __init__(self, name, service_mu, service_sigma, service_dist):
        super().__init__(name, self.payService)
        self.name = name
        self.service_mu = service_mu
        self.service_sigma = service_sigma
        self.service_dist = service_dist

    # the paying service uses the distributions available through the rng 
    # method sampleRV

    def payService(self, cust):
        # service time
        return sampleRV(self.service_mu, self.service_sigma, self.service_dist)

# A PickupStation is a queue where a customer waits for their order to complete,
# and leaves when it is finished.  Distribution parameters of the time between when
# the customer arrives at the station and when the order is delivered are passed,
# as is a function to call when the customer departs the station.


class PickupStation(ModelQueue):

    def __init__(self, name, service_mu, service_sigma, service_dist, report_exit):
        # The construction parameters for a ModelQueue are the service function to call,
        # and the customer departure function to call
        super().__init__(name, self.pickupService, report_exit=report_exit)
        self.name = name
        self.service_mu = service_mu
        self.service_sigma = service_sigma
        self.service_dist = service_dist
        self.report_exit = report_exit

    # The service time for the pickup uses the rng sampling code 'sampleRV'
    # passing in the distributional parameters

    def pickupService(self, cust):
        return sampleRV(self.service_mu, self.service_sigma, self.service_dist)


# ReportError is called on discovering of some error that halts
# execution, printing a message describing that error and then
# exiting

def ReportError(msg):
    print(msg)
    exit(1)

# Method getArgs sets up the argparse arguments for scanning the command line,
# gets the command line arguments, and validates them.

def getArgs():

    # A number of global variables are set as a result of parsing the command line
    # and need to be declared as global to get that scope correct
    global ARRIVAL_RATE, SERVING_LIMIT, MIN_ORDER, MAX_ORDER, TERMINATION, SEED, Topo_dict

    # Declare all the command line arguments that are possible or expected
    parser = argparse.ArgumentParser()
    parser.add_argument(u'-arrival_rate', metavar=u'Poisson arrival rate of new customers',
                        dest=u'arrival_rate', required=True)
    parser.add_argument(
        u'-min_order', metavar=u'maximum number of items a customer may order', dest='min_order', required=False)

    parser.add_argument(
        u'-max_order', metavar=u'maximum number of items a customer may order', dest='max_order', required=False)

    parser.add_argument(u'-termination', metavar=u'length of simulation run (in seconds)',
                        dest=u'termination', required=True)

    parser.add_argument(u'-serving_limit', metavar=u'maximum number of customers that may be in system',
                        dest=u'serving_limit', required=True)

    parser.add_argument(
        u'-seed', metavar=u'random number generator initialization', dest=u'seed', required=False)

    parser.add_argument(
        u'-topo', metavar=u'json file describing topoology', dest=u'topo_file', required=True)

    # Get command line argument file, if present
    cmdline = sys.argv[1:]
    cmdline = []

    # A common technique I use is to put all the command line arguments
    # in a file, one per line, and then on the command line indicate
    # this by a '-is argument_file' command that is identified before
    # argparse is called, and a command-line list is built up from
    # the contents of the argument file

    if len(sys.argv) == 3 and sys.argv[1] == "-is":
        with open(sys.argv[2], "r") as rf:
            for line in rf:
                line = line.strip()
                if len(line) == 0 or line.startswith('#'):
                    continue
                if line.find("#") > -1:
                    cut = line.find("#")
                    line = line[:cut]
                cmdline.extend(line.split())
    else:
        cmdline = sys.argv[1:]

    # The list 'cmdline' is now either what was on the command line,
    # or is built out of what was in the arguments file.  This is passed
    # to the argparse parser

    args = parser.parse_args(cmdline)

    # Various command line arguments are validated now.
    # Typically, to test whether the input string is a floating point
    # number or integer, we use the python try/except mechanism.
    try:
        ARRIVAL_RATE = float(args.arrival_rate)

        # args.arrival_rate passed the 'is it a floating point number' test.
        # It needs also to pass the 'is it a positive number' test
        if not ARRIVAL_RATE > 0.0:
            ReportError(f"Arrival rate {args.arrival_rate} is not positive")

    except:
        print(f"Arrival rate {args.arrival_rate} needs to be positive")
        exit(1)

    try:
        TERMINATION = float(args.termination)

        # args.termination passed the 'is it a floating point number' test.
        # It needs also to pass the 'is it a positive number' test
        if not TERMINATION > 0.0:
            ReportError(f"Arrival rate {args.termination} is not positive")

    except:
        print(f"Arrival rate {args.termination} needs to be positive")
        exit(1)

    try:
        SERVING_LIMIT = int(args.serving_limit)

        # args.serving_limit passed the 'is it an integer' test.
        # It needs also to pass the 'is it a positive integer' test
        if not SERVING_LIMIT > 0:
            ReportError(
                f"Waiting limit {args.serving_limit} not positive integer")
    except:
        ReportError(f"Waiting limit {args.serving_limit} not positive integer")

    try:
        if args.min_order is not None:
            MIN_ORDER = int(args.min_order)

            # args.min_order passed the 'is it an integer' test.
            # It needs also to pass the 'is it a positive integer' test
            if not MIN_ORDER > 0:
                ReportError(
                    f"Customer maximum order {args.min_order} not positive integer")
    except:
        ReportError(
            f"Customer maximum order {args.min_order} not positive integer")

    try:
        if args.max_order is not None:
            MAX_ORDER = int(args.max_order)

            # args.max_order passed the 'is it an integer' test.
            # It needs also to pass the 'is it a positive integer' test
            if not MAX_ORDER > 0:
                ReportError(
                    f"Customer maximum order {args.max_order} not positive integer")
    except:
        ReportError(
            f"Customer maximum order {args.max_order} not positive integer")

    # Test for limit bounds inversion
    if MAX_ORDER < MIN_ORDER:
        ReportError(f"Max order size {MAX_ORDER} < min order size {MIN_ORDER}")

    # set the random number generator with a seed so that repeated runs
    # from the same input file start the random number generation sequence
    # at the same place
    if args.seed is not None:
        SEED = args.seed
    random.seed(SEED)

    # Check for the presence of the named input file.
    if not os.path.exists(args.topo_file):
        ReportError(f"Topology file {args.topo_file} does not exist")

    # Read in a json dictionary from the input file.
    with open(args.topo_file, 'r') as rf:
        Topo_dict = json.load(rf)


# ValidateDict tests elements read in for a dictionary that will be used
# to initialize a class constructor. It primarily tests the types and
# positivity of the values

def ValidateDict(d, keys, ints, floats, dists, consts, objs=()):
    errs = []

    # Variable d is the dictionary. The list 'keys' names strings
    # that are expected to be indices into the dictionary
    for key in keys:
        if key not in d:
            errs.append(f"expected attribute {key} is absent")

    if len(errs) == 0:
        # All the expected keys are present.  For every key named in list
        # 'ints' ensure that the value of the dictionary for that key is
        # indeed a positive integer.  Use the python try/except mechanism 
        # value type, and then test value positivity.
        for intkey in ints:
            try:
                value = int(d[intkey])
                if not value > 0:
                    errs.append(
                        f"expected attribute {intkey} value to be positive")
            except:
                errs.append(f"expected attribute {intkey} value to integer")

       
        # Do the same test for keys identified as names for floating point
        # numbers. 
        for floatkey in floats:
            try:
                value = float(d[floatkey])
                if not value > 0:
                    errs.append(
                        f"expected attribute {floatkey} value to be positive")
            except:
                errs.append(
                    f"expected attribute {floatkey} value to be numeric")

    # There are string constants that constrain what values are to be expected,
    # here associated with names of probability distributions.
    # Ensure that every key drawn from that list has a value from a list of expected
    # values.

    for distrb in dists:
        if not d[distrb] in consts:
            errs.append(f"unexpected distribution {d[distrb]}")

    return ','.join(errs)


# ValidateModelQueue validates dictionaries describing model queue elements
# MenuStation, PayStation, and PickupStation descriptions all use this

def ValidateModelQueue(tsd):
    keys = ('name', 'service_mu', 'service_sigma', 'service_dist')
    ints = ()
    floats = ('service_mu', 'service_sigma')
    dists = ('service_dist',)
    consts = ('expon', 'uniform', 'gaussian')
    return ValidateDict(tsd, keys, ints, floats, dists, consts)

# BuildTopo instantiates the variables representing the MenuStation,
# PayStation, and PickupStation class instances.
# When called the Topo_dict dictionary has already been read in from
# the input json file.

def BuildTopo():

    # The variables holding instances of classes are all global
    global custStrm, MenuStations, pay_station, pickup_station

    # Focus on the json description of the pickup station
    pkd = Topo_dict['pickup_station']

    # Make sure the pickup station dictionary has what is needed, in the data
    # types and positivity that is needed.  
    err_msg = ValidateModelQueue(pkd)
    if len(err_msg) > 0:
        ReportError(f"PickupStation configuration error {err_msg}")

    # The pickup station configuration is validated, so build it.
    # Note in particular that because there will be no model queue
    # taking a departing customer as input, we identify a method
    # to call when the customer has finished service. The pay station
    # initialization needs to know where its output goes, so 
    # we build the station objects in reverse order of what the
    # customer visits
    #
    pickup_station = PickupStation(pkd['name'], pkd['service_mu'],
                                   pkd['service_sigma'], pkd['service_dist'], report_exit=custStrm.departCust)

    # Focus on the json description of the pay_station 
    #
    pyd = Topo_dict['pay_station']

    # Make sure the pay station dictionary has what is needed, in the data
    # types and positivity that is needed 
    #
    err_msg = ValidateModelQueue(pyd)
    if len(err_msg) > 0:
        ReportError(f"PayStation configuration error {err_msg}")

    # Build the pay_station object; its construction parameters 
    # describe its service distribution
    #
    pay_station = PayStation(pyd['name'], pyd['service_mu'],
                             pyd['service_sigma'], pyd['service_dist'])

    # Include the previously created pickup station object as an output
    # for the pay station.
    #
    pay_station.addOutput(pickup_station)

    # Ultimately an error message will cause a call to ReportError
    # and exit of the program, but we'll test the configuration dictionary
    # of each menu station, save any error messages, and report all of those
    # presented as a group.
    #
    err_msgs = []

    # The configuration dictionary has a list of dictionaries, one per
    # menu station.
    #
    for msd in Topo_dict['menu_stations']:

        # Validate _this_ menu station's parameters.
        err_msg = ValidateModelQueue(msd)

        # If a non-empty error message is returned, save it
        # to be bundled into a single message containing all
        # the error messages from menu station configurations.
        #
        if len(err_msg) > 0:
            err_msgs.append(err_msg)

        else:
            # Build the validated menu station object.
            ms = MenuStation(msd['name'], msd['service_mu'],
                             msd['service_sigma'], msd['service_dist'])

            # Remember the object in a global list of all menu stations.
            MenuStations.append(ms)

            # Tell the menu station object that its output goes to the
            # pay_station object
            #
            ms.addOutput(pay_station)

            # Tell the CustomerStream object that _its_ output can go to
            # this menu station object.
            #
            custStrm.addOutput(ms)

    # If any errors were encounted in parsing the menu station dictionaries,
    # combine them into a single string, error messages separated by commas,
    # and call ReportError with that string
    #
    if len(err_msgs) > 0:
        err_msg = ','.join(err_msgs)
        ReportError("MenuStation error(s) {err_msg}")

# The main program gives the highest level description of control
# of the simulation execution

def main():

    # the pointer to the customer stream needs to be global
    # because the constructor of the pickup station needs to
    # reference its departCust method.
    #
    global custStrm

    # getArgs brings in the command line arguments
    # and sets values for global variables used in 
    # various object's constructors.
    getArgs()

    # start the random number stream with the specified seed,
    # this call needs to be made before any calls to the python
    # random number generators.
    #
    random.seed(SEED)

    # Create an object that generates a stream of customers.
    # The object needs to be created before the call to BuildTopo
    # because the PickupStation constructor parameters include a
    # pointer to the custStrm
    #
    custStrm = CustomerStream("customer stream", ARRIVAL_RATE, SERVING_LIMIT)

    # Schedule the first customer arrival, after one sampled
    # inter-arrival delay.
    #
    custStrm.NewCustomer(True, None)

    # Create the various objects for the simulation, and connect
    # outputs and inputs.
    #
    BuildTopo()

    # Start the execution time of the simulation, to advance under
    # the input parameter giving the end simulation time 'TERMINATION'
    # is reached.
    #
    EvtMgr.Run(TERMINATION)

    # Now that the simulation run has finished, report statistics.
    # First the statistics on the number of arrivals and discouraged arrivals.
    #
    custStrm.ReportArrivals()


    # Now report on the overall delay experienced by a customer,
    # from arrival to departure.
    #
    custStrm.trace.StatSummary()

    # Report the statistics on time customers spend
    # at a menu station, including waiting to be served.
    for ms in MenuStations:
        ms.trace.StatSummary()

    # Report the statistics on time customers spend
    # at the pay station, including waiting to be served.
    #
    pay_station.trace.StatSummary()

    # Report the statistics on time customers spend
    # at the pickup station, including waiting to be served.
    #
    pickup_station.trace.StatSummary()


# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    main()

