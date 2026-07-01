# The ModelQueue class implements a FCFS queue.
# One of its parameters is a function whose argument
# is an element drawn from the model queue's list,
# which returns a virtual time value that indicates
# what the delay associated with giving service to that element
# is.  Note the important assumption that that service time can be
# predicted at the point the element goes into service
#

from evt import EvtMgr, EvtFunc
from stats import Trace
from vrt import VT, VTZero

mqID = 0
def NxtID():
    global mqID
    mqID += 1
    return mqID

class ModelQueue():
    # Construction parameters are the name, a pointer to a function to call
    # that returns a service time for a customer joining the queue, and optionally
    # a pointer to a function that is called when an exiting customer has no-where
    # to go.
    def __init__(self, name, service_func, report_exit=None):

        # remember text identifier
        self.name = name

        # acquire unique identity among model queue instantiations
        self.ID = NxtID()

        # in_service will hold the customer getting service, is otherwise None.
        self.in_service = None

        # queued is the FCFS list of customers at the queue.
        self.queued = []

        # outputs is a list of potential 'next queue's that a customer may be
        # routed to.  This implementation cycles between then evenly, other
        # implementations might change this, e.g., probabilistically choose one.
        #
        self.outputs = []

        # output_idx is used to select the next output to direct a customer through.
        self.output_idx = 0

        # Remember the pointer to the function that returns the service time.
        self.service_func = service_func

        # Remember the pointer to the function to call self.outputs is empty.
        self.report_exit = report_exit

        # Set up a trace of customer times entering and leaving the queue.
        self.trace = Trace(name)

    # When the ModelQueue instance is created we do not assume that the objects
    # to which customers are directed are known and can be included with the constructor.
    # The addOutput method is later called to include an output destination to the self.outputs
    # list

    def addOutput(self, output):
        self.outputs.append(output)

    # When there is a customer to add to this model queue, the code
    # holding that customer calls the method custArrival to attach it to
    # the model queue.

    def custArrival(self, cust):

        # Record the arrival time of this customer to the queue.
        self.AddObs("start", EvtMgr.NowInSecs(), cust.customerID)

        # When there is a customer already in service the new arrival
        # joins the self.queue list
        #
        if self.in_service is not None:
            self.queued.append(cust)
            return

        # The customer arrived to an empty queue, and goes immediately into
        # service.  Details for that are handled by method start_service.
        self.start_service(cust)

    # start_service is called with the customer to go now into service.
    # That customer is not (or no longer) in self.queued list.

    def start_service(self, cust):

        # prepare to schedule the end_service event handler by creating
        # an EvtFunc instance for it.
        evt_func = EvtFunc(cust, None, self.end_service)

        # save the cust receiving service in self.in_service, to be recovered
        # when the customer leaves service.
        #
        self.in_service = cust

        # Call the self.service_func function to get a service time.  That
        # time may depend on attributes of the customer, so that is included as
        # a parameter.   The function is assumed to return a floating point number in units of
        # seconds, and so needs to be converted into a VT virtual time representation.
        #
        vt_delay = VT.from_secs(self.service_func(cust))

        # Schedule the end_service event to execute after the service time.
        EvtMgr.AddEvt(evt_func, vt_delay,
                      desc=f"{self.name} end service for cust {cust.customerID}")

    # The end_service event handler is called to implement the departure of a customer
    # from the queue.  As an event handler it has two input parameters, but only one
    # of this (cust == context) is non-None.  In fact, its presence is unnecessary because
    # that same customer is resident in self.in_service.  It can be helpful when stepping code
    # through debugging to see the cust in the event while still in the event list.

    def end_service(self, cust, none):

        # Record that the customer has completed service here.
        self.AddObs("stop", EvtMgr.NowInSecs(), self.in_service.customerID)

        # If there are output outlets for the customer, choose 'the next' one.
        if len(self.outputs) > 0:
            outputs = len(self.outputs)

            # self.output_idx essentially counts the number of customers pushed
            # out of the queue to date, and takes the remainder mod number-of-outputs
            # to choose the output to which the customer is directed.
            idx = self.output_idx % outputs
            self.output_idx += 1

            # The output is assumed to be another ModelQueue, and so has
            # a custArrival method to call directly.
            #
            self.outputs[idx].custArrival(self.in_service)

        # Control reaches here if there are no outputs configured. If the model queue
        # is configured to report this with a call to self.in_service, do so.
        elif self.report_exit is not None:
            self.report_exit(self.in_service)

        # Remove cust from self.in_service.
        self.in_service = None

        # When the queue is non-empty we need to remove the first element and
        # put it into service.
        #
        if len(self.queued) > 0:

            # Recover the next customer.
            cust = self.queued[0]

            # Adjust the self.queue list to reflect removal of the first element.
            self.queued = self.queued[1:]

            # Directly call the model queue's own start_service method to put
            # the customer into service.
            #
            self.start_service(cust)

    # The AddObs method is called to report customer arrivals and departures.

    def AddObs(self, obs_type, time, custID):
        self.trace.AddObs(obs_type, time, custID)

    # InSystem returns the number of customers in the system, which is 0 if the
    # queue is empty and no customer is in service, is 1 if the queue is empty
    # and there is a customer in service, or is 1 plus the number of customers in the
    # queue.

    def InSystem(self):
        if self.in_service is None:
            return 0
        return len(self.queued)+1
