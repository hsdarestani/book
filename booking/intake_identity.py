"""Match public intake to one Book patient by >=3 of five *present* fields.

Never silently merge duplicate profiles, change existing contact credentials,
or expose an old clinical file to the unauthenticated submitter.
"""
from datetime import date
from .customer_identity import normalize_email, normalize_name, normalize_phone
from .models import Customer


def identity_values(data):
    def get(field):
        return data.get(field) if isinstance(data, dict) else getattr(data, field, None)
    dob=get('date_of_birth')
    if isinstance(dob, date): dob=dob.isoformat()
    dob=str(dob or '').strip()
    if dob and (len(dob)!=10 or dob[4]!='-' or dob[7]!='-'):
        dob=''
    return (
        normalize_name(get('first_name')),
        normalize_name(get('last_name')),
        normalize_phone(get('phone')),
        dob,
        normalize_email(get('email')),
    )


def match_score(left, right):
    return sum(1 for a,b in zip(identity_values(left),identity_values(right)) if a and b and a==b)


def locate_unique_intake_patient(data):
    """Return (customer, conflict). No match means caller may create new.

    Ambiguous matches, or contact overlap with insufficient confirmation,
    require staff review rather than guessing or creating a duplicate.
    """
    incoming = identity_values(data)
    if not incoming[0] or not incoming[1] or not incoming[4]:
        return None,'missing_identity'
    customers=list(Customer.objects.order_by('pk'))
    matching=[p for p in customers if match_score(data,p)>=3]
    if len(matching)>1:
        return None,'multiple_three_of_five_matches'
    if len(matching)==1:
        chosen=matching[0]
        # A contact point belonging to another record creates ambiguity.
        for other in customers:
            if other.pk==chosen.pk:continue
            values=identity_values(other)
            if any(incoming[i] and incoming[i]==values[i] for i in (2,4)):
                return None,'contact_collision'
        return chosen,''
    for other in customers:
        values=identity_values(other)
        if any(incoming[i] and incoming[i]==values[i] for i in (2,4)):
            return None,'insufficient_identity_evidence'
    return None,''
