# ML helper module
model = None

def predict(features_dict):
    """
    features_dict: dict or list of features in order expected by model
    returns: probability of fraud (float between 0 and 1)
    """
    if model is None:
        raise RuntimeError("Model not loaded")
    import numpy as np
    # assuming model expects 2D array
    X = np.array([list(features_dict.values())])
    prob = model.predict_proba(X)[:,1][0]
    return float(prob)
