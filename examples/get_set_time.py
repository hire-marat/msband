import logging
import datetime as dt
from msband.static.command import *
from msband.protocol import ProtocolInterface


# Connect using your preferred interface
iband: ProtocolInterface = ...


# Get current time in UTC
band_time = iband.command(TimeGetUtcTime)

# Set UTC time from computer clock
if dt.datetime.utcnow().year < 2012:
    logging.warning("Band doesn't like to exist before 2012, you may get an error")

iband.command(TimeSetUtcTime, NewTime=dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc))
